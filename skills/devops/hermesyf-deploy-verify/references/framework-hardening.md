# 契约框架加固对照表（声明 ≠ 强制）

`hermesyf-deploy-verify` 检查的是「部署是否生效」，这里补的是「代码里的门是不是真门」。
判断标准只有一条：**把这条约束删掉，会不会有一次真实的越界发包/假汇报因此发生。**
不会 = 只是注释，不是门。

实例都在 `HermesYF/yf_tools/task_contract.py` 与 `assessment_run.py`。

## 1. scope 匹配：`startswith` 一定会被骗

```python
# ❌ before：a.com 的 scope 放行 a.com.evil.net；带路径的变体也会漏
def in_scope(host: str, scope: list[str]) -> bool:
    return any(host.startswith(s) for s in scope)

# ✅ after：先取 hostname，再精确/通配/CIDR 三分支，且通配只认一条点边界
def in_scope(host: str, scope: list[str]) -> bool:
    h = urlsplit(host if "://" in host else f"//{host}", scheme="//").hostname or ""
    h = h.rstrip(".").lower()
    for s in scope:
        s = (s or "").strip().lower().rstrip(".")
        if not s:
            continue
        if s.startswith("*."):                      # 通配子域，不含裸域
            if h.endswith(s[1:]) and h != s[2:]:
                return True
        elif "/" in s or s.count(":") and not s.replace(".", "").isdigit():
            if _ip_in_cidr(h, s):                   # 10.0.0.0/8 之类
                return True
        else:
            if h == s:
                return True
    return False
```

要验的三条：
- `a.com.evil.net` 对 scope `a.com` → **False**（不是 True）。
- `a.com@evil.net`、`//a.com/../evil.net` → 取 hostname 后为 `evil.net` → **False**。
- 通配 `*.a.com` 匹配 `x.a.com` 但**不匹配** `a.com` 本身（裸域要单独写）。

## 2. 执行器必须 fail-closed，不是「记一笔继续跑」

```python
# ❌ before：scope 为空字符串 = 不限制（等于全放行）
if contract.scope and not in_scope(target, contract.scope):
    warn("out of scope, continuing")

# ✅ after：没有 scope = 拒绝；越界 = 抛异常，调用方无法忽略
if not contract.scope:
    raise ContractError("契约没有 scope，拒绝发包（先 set --scope）")
if not in_scope(target, contract.scope):
    raise ContractError(f"目标不在 scope 内: {target}")
if contract.get("allowed_override") is False and not in_scope(...):
    ...
```

相关的一条：`assessment_run --contract` 会**强制**校验目标在 scope 内，越界直接抛异常，不发包。
「有 warning 但继续」是最坏的形态——日志里脏，行为上照样打出去。

## 3. 出口：写了 `egress` ≠ 流量走这个出口

| 层 | 声明（可伪造） | 强制（可验证） |
|---|---|---|
| 代理 | 契约里 `egress: 127.0.0.1:7890` | `urllib`/`httpx` 显式 `proxy=`，并先打 `api.ipify.org` 记下出口 IP 进证据 |
| TUN | 配置里有 `tun.enable: true` | `curl --noproxy '*' https://api.ipify.org` 仍返回节点 IP |
| socks5 | `--egress-socks5` 字符串 | naabu/scanner 真正带 `-proxy socks5://...`，且进程失败时不回落直连 |

汇报时分开写：**「已强制」（有对照实验）/「仅记录」（契约字段）。** 把后者说成安全边界，
就是把自己的假设当成事实交给么西么西。

`--ports` 这类会产生大量外部发包的动作，要求契约里**显式**写 `egress_socks5`，
不允许从 `egress` 推断——否则一个 HTTP 代理字段会被当成「扫描也走代理」的证据。

## 4. 发现：`confirmed` 必须绑到具体证据

```python
# ❌ before：只要有任意一条 evidence 存在，就能把 finding 标成已复现
if status == "confirmed" and not data.get("evidence"):
    raise ContractError("confirmed 需要证据")

# ✅ after：evidence_ids 必填、逐个校验存在；未登记 = 拒绝
if status == "confirmed":
    if not ids:
        raise ContractError("confirmed finding 必须 --evidence 绑定证据 ID")
    missing = [i for i in ids if i not in {e["id"] for e in data.get("evidence") or []}]
    if missing:
        raise ContractError(f"evidence id 不存在: {missing}")
```

同一原则套到 `done`：「填一个 done 数字」等于自称做过，所以 `done` 由 `done_items`
自动推导，每项必须挂证据（`add_done(... evidence=[...])`），`planned` 封顶。

## 5. 交付门（`close`）必须能真的拒绝

`close` 至少要挡住这四类：

1. 证据文件被删/哈希变了（登记时算 sha256，close 时重算比对）。
2. `planned != done + skipped`（漏覆盖）。
3. 声明的交付物没有登记成证据（报告写了，文件不存在）。
4. `findings` 里有 `confirmed` 但没绑 evidence id。

```python
# verify() 返回未满足条件列表；空列表才允许 delivered
def verify(data):
    problems = []
    cov = data.get("coverage") or {}
    if int(cov.get("planned") or 0) != int(cov.get("done") or 0) + len(cov.get("skipped") or []):
        problems.append("planned 对不上 done+skipped")
    for e in data.get("evidence") or []:
        p = e.get("path")
        if not p or not os.path.isfile(p):
            problems.append(f"证据文件不存在: {p}")
        elif e.get("sha256") and sha256_of(p) != e["sha256"]:
            problems.append(f"证据哈希变了: {p}")
    for f in data.get("findings") or []:
        if f.get("status") == "confirmed" and not f.get("evidence_ids"):
            problems.append(f"confirmed 但无证据: {f.get('id')}")
    return problems
```

## 6. 只读门禁与封存

- `delivered` 状态的契约**只读**：任何 `set/evidence/finding` 写入直接拒绝，先 `reopen`。
- `reopen` 前后要留快照（内容哈希），否则「交付后又改数据」无从证明。
- `closeout` 逐成员哈希 + 唯一目录 + 加锁：两个会话同时收尾会互相覆盖。

## 7. 自查清单（改完这些代码就跑一遍）

- [ ] `in_scope("a.com.evil.net")` 对 `a.com` 返回 False
- [ ] 空 scope 时执行器抛异常，不是默认放行
- [ ] 越界目标会让 `assessment_run` 抛异常且**没有包发出**（抓包/日志确认）
- [ ] 出口 IP 有对照实验证据（`--noproxy '*'` 与走代理各一次）
- [ ] `confirmed` 不绑 evidence id 被拒绝
- [ ] 改一个证据字节后 `close` 失败
- [ ] `delivered` 状态下写入被拒绝
- [ ] 汇报里「已强制」只出现在做过对照实验的条目上
