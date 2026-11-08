---
name: egress-ip-rotation
description: "Use when a target blocks your IP or you spray creds."
version: 1.0.0
author: "么西么西"
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [proxy, mihomo, ip-block, egress, rate-limit, waf]
    related_skills: [blitzstrike-workflow, web-hunting, seagull-pentest]
---

# 出口 IP 管理与轮换

渗透里「打不动」最后多数不是漏洞问题，是出口 IP 问题：被整段封、被按设备指纹封、三台机器其实是同一个 IP。这个技能管两件事：**验证出口**和**真正换掉出口**。

## When to Use

- 任何爆破/扫描/枚举**之前**（强制，不是建议）
- 撞库/凭据填充开跑前：先定出口分散方案和分片，再谈并发
- 目标返回 403 / 429 / `{"blocked":true}`，但从别的链路又能访问
- 要把任务分发到多台机器并行
- 手上有一堆代理节点，不知道哪些真能用、是不是同一个段

## 铁律

1. **爆破/扫描前先验出口**：
   ```bash
   curl -s -m 15 -x http://127.0.0.1:7890 https://api.ipify.org
   curl -s -m 15 --noproxy '*' https://api.ipify.org     # 对照直连
   ```
   两个结果相同 = 代理没生效或节点回连本机，等于裸奔。
2. **分发到多台机器前，逐台验出口**：
   ```bash
   ssh host 'curl -s -m 10 https://api.ipify.org'
   ```
   **出口同段 = 没分发**，只是把同样的量打了三倍，封得更快。所谓的「几个小弟一起上」，先确认它们不是同一个 IP。

反向也成立：**批量任务（撞库/枚举/拉号）默认就要分片到全部可用机器**，先扣掉已完成的再交错切，单机跑三万条会被当成没干活。分片骨架见 `templates/spray_shard.py`。
3. **先小批量验证通路，再全量**：200 条跑通再跑 3 万条；全量跑完才发现 100% block 是浪费。

## 判断封禁层级（决定换 IP 有没有意义）

| 现象 | 含义 | 应对 |
|---|---|---|
| 主站 200，API 全 403 `{"blocked":true}` | API 有**自己的 IP 黑名单**，与 CDN/WAF 无关 | 换 IP 段（住宅），或放弃这条 API 通道 |
| 全路径 403 + CF 挑战页 | CF 按 IP/UA 判定 | 过盾（浏览器 + 坐标点击）或换 IP |
| 新 UUID + 新 UA 仍 403 | 不是设备指纹，是 IP | 同上 |
| 冷却 30min 后单发仍 403 | 不是频率，是黑名单 | 同上 |
| 整批节点 100% block | 同 ASN / 同段被封（机场常见） | 换 ASN，不是换节点 |
| 只有部分 403、隔一会恢复 | 频率封 | 降并发、加抖动即可 |
| **curl/requests 全 403，同 IP 同节点上浏览器 200** | **TLS 指纹（JA3/JA4）拦截非浏览器客户端**，与 IP 无关 | 不要继续换 IP。先用 `curl_cffi` 的 `impersonate` 复刻浏览器指纹（见下节），只有必须执行 JS 时才动浏览器 |
| API 403 但同一 body 换个客户端就 200 | 同上：先比对**请求头与 TLS 层**，再怀疑 IP | 抓浏览器真实请求的 header 逐项对齐；body 一致却仍 403 → 就是 TLS 指纹 |

**区分频率封和段封**：并发测一批节点，全 403 且新 UUID 也 403 → 段封；部分通过、间隔后恢复 → 频率封。

**浏览器也要一起测**：某些站对 curl 单请求放行、对浏览器（几十个资源请求）直接整页拦截。判断封禁时两条链路都跑一遍，否则会把「浏览器被拦」误判成「IP 没封」。

## 过 TLS 指纹：curl_cffi 优先于浏览器

确认是 TLS 指纹后，**第一选择是 `curl_cffi`，不是开浏览器**。浏览器自动化要跑整套 JS、慢、占内存，而且产物没法塞进纯脚本（TVBox spider、批处理、CI）里；`curl_cffi` 只是一层 HTTP 客户端，能直接进任何 Python 代码。

```bash
pip install curl_cffi
```

```python
from curl_cffi import requests as cr
s = cr.Session(impersonate="chrome", verify=False)   # 也可 chrome124/chrome131/safari17_0
s.headers.update({"Origin": "https://target", "Referer": "https://target/"})
r = s.post(url, json=body, timeout=25)
```

- **只加业务头**（Origin/Referer/Cookie）。`impersonate` 已经带了一整套与 JA3 匹配的 UA / sec-ch-ua / ALPN，**别自己再设 `User-Agent` 和 `Accept`** —— 覆盖后指纹与请求头不自洽，是最容易踩的自伤。
- 多试几个 `impersonate` 值（`chrome` / `chrome131` / `safari17_0`）再下结论；有些网关只放行特定浏览器族。
- **目标环境装不上 `curl_cffi`**（Android/TVBox 的 ChaquoPy、嵌入式 Python、交付给别人的单文件脚本）：不要退回 `requests`（必 403），也不要架中转服务多一个进程。手写一个 TLS 1.3 客户端内嵌进交付物——Chrome 风格 ClientHello + 自实现 X25519/AES-GCM 约 350 行，实测能过同一道网关。骨架、四个致命坑与自测向量见 `tvbox-spider-dev` 技能里的 `tls-fingerprint-client` 参考文档。
- 过了 TLS 指纹这一关，**原来的 IP 白名单结论要重新验**：本次实测同一批机房节点在 `curl_cffi` 下全部 200，此前「整段封 IP」的判断是错的。TLS 指纹被封时最容易被误读成 IP 封——先换客户端，再换 IP。

### 必须开浏览器时：DrissionPage + Edge 的固定姿势

`curl_cffi` 过不去（要跑 JS、要真 Cookie、要过挑战）才动浏览器。这就是么西么西说的「破盾那一套」，不要每次重新摸索：

```python
from DrissionPage import ChromiumOptions, ChromiumPage
co = ChromiumOptions()
co.set_browser_path("/usr/bin/microsoft-edge")
co.headless(True)
co.set_argument("--no-sandbox"); co.set_argument("--disable-dev-shm-usage")
co.set_proxy("http://127.0.0.1:7890")
page = ChromiumPage(co)
page.listen.start("api")        # 必须先于 page.get()
page.get(URL)
```

四个会卡住的点：

- **4.1.x 的 API 是 `set_address()`，不是 `remote_address()`**。写旧名直接 `AttributeError`。
- **让它自己启动浏览器，不要外挂 CDP**。先自己开一个 `--remote-debugging-port` 再 `set_address` 连，经常在 devtools 握手阶段挂掉（`Handshake status 404` / `BrowserConnectError`）。`set_browser_path` + `headless(True)` + `set_proxy` 让它自己管生命周期最稳。
- **`page.listen.start()` 必须在 `page.goto()` 之前**，否则页面加载期的那几个关键请求（配置、鉴权、登录）全部漏掉，后面只能靠猜。
- **先看浏览器能不能通，再下「封 IP」结论**。同一 IP 上浏览器 200、脚本 403 就是指纹问题；浏览器也 `ERR_CONNECTION_CLOSED` 就真是服务端在拦（地区白名单 / 连接层封）。

另一条路是 Playwright 自带 chromium（`playwright install chromium`，版本与库自匹配，也不用外挂 CDP）：监听用 `page.on("request", fn)` 拿 `post_data`，HTML 用 `page.content()`（不是 `page.html`）。两条路都行，优先用已经装好的那条，不要在环境上反复折腾。

## IP 伪造头：几秒钟试完，基本无效

```python
for h in ({"X-Forwarded-For":"1.1.1.1"}, {"X-Real-IP":"1.1.1.1"},
          {"X-Client-IP":"1.1.1.1"}, {"True-Client-IP":"1.1.1.1"}):
```

真实 WAF 取 TCP 对端 IP，这些头只在有反代且配置错误时生效。`CF-Connecting-IP` 会被 CF 自己消费（回 CF 拦截页），不要浪费一次请求。

## 换 IP 的操作

- mihomo 多节点并发探测、常驻轮换池、组/节点切换、协议与 DNS 陷阱：见 `references/mihomo-node-rotation.md`
- 高并发凭据填充（撞库）的端点定位、鉴权头形状、分类与分发：见 `references/credential-stuffing.md`
- 可直接复制改常量的分片跑机骨架：`templates/spray_shard.py`

**先确认「换节点」真的换了 ASN**：机场的「香港优选」这类组常常 20 个节点全在同一机房同一段，组内切换等于没切。要看 `GLOBAL` 的全量节点列表，挑不同国家/不同 ASN 的。

**订阅前先看节点服务器落在哪个段**：服务器 IP 是国内 ISP（`112.65.x` 联通、
`183.61.x` 电信这类）→ 这是「国内中转」订阅，设计路径是国内客户端 → 国内中转机
→ 海外落地。它在用户家宽上能用，在海外服务器上永远不能用：TCP 握得通，但协议
握手 5 秒超时、服务器不回包。换哪个节点都一样，别在节点上反复试——直接判定
「此订阅需在目标方本地网络运行」，并把验证脚本交给对方。

**整批节点突然全不可用，先查 DNS 再怀疑节点**：主实例开 fake-ip 时会把**系统级**解析吐成 `198.18.x`，新起的测试实例拿到假地址必然连不上，表现是「N 个订阅全部阵亡」。判据是节点连接日志里出现 `dial tcp 198.18.0.x:PORT`。处理见 `references/mihomo-node-rotation.md` 的 DNS 陷阱节——别在节点上反复换。

**主二进制只读**：需要新内核才支持的协议（anytls / hysteria2）时，把二进制 `cp` 一份到独立目录、在副本上换版本测试，测完删掉副本并在汇报里说明；**不要覆盖用户主进程用的那一份**——换掉会连带改变他自己全部的代理行为，而且他随时会要求换回来。

## 换不动时怎么收场

按这个顺序判断还值不值得投入：

1. **住宅 IP 是否可得**？家宽 / 4G 热点 / 住宅代理。机房 IP 段被整段封时，这是唯一出路——不是技术问题，是资源问题。
2. **目标的核心价值是否依赖被封的那条通道**？登录、数据、上传全走被封的 API → 换不掉就等于打不动，不要继续在节点上耗。
3. **换目标。**

交付姿态：把结论和「需要什么资源才能继续」一次说清（要住宅代理就给格式 `socks5://user:pass@ip:port`），并附一个能在对方本地网络直接跑的验证脚本，而不是反复描述尝试过程。
