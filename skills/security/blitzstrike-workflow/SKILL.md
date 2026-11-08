---
name: blitzstrike-workflow
description: "Use when starting a pentest: tool-by-phase map."
version: 1.0.0
author: "么西么西"
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [blitzstrike, workflow, tooling, mcp]
    related_skills: [seagull-pentest, web-app-pentest, aspnet-webforms-panel-pentest]
---

# BlitzStrike 工具编排

开工前先对照这张表选工具，别默认手工硬献。141 个外部工具 + 188 个 MCP 工具都在，但**不查就等于没有**。

## When to Use

- 接到任何新目标（域名/IP/APK/代码库）开工的第 0 步
- 手工干到卡住时，回来查一遍有没有对应工具能绕

## 阶段 → 工具映射

| 阶段 | 先试这些 MCP 工具 | 再试外部工具 |
|---|---|---|
| 资产测绘 | — | **么西么西 FOFA Worker**（`fofa_cli.py`，见下节） |
| 侦察/指纹 | `live_recon`、`asset_discovery`、`active_scan`、`detect_framework`、`detect_waf` | httpx、whatweb、wafw00f、subfinder、amass |
| 端口 | `port_correlation` | naabu、nmap、rustscan（**别手写 python socket**） |
| 端点/参数 | `param_surface`、`surface_map`、`eagle_eye` | katana、gau、subjs、arjun、ffuf、feroxbuster |
| JS/前端 | `frontend-api-recon` 技能 | subjs、gau、katana、trufflehog |
| APK/客户端 | `mobile-app-scan` 技能 | apkleaks、jadx、apktool、frida、mobsf |
| 盲注/盲RCE | `blind_oracle` → `blind_sqli_confirm` | sqlmap、commix、tplmap |
| XSS | `blind_oracle`(sink) → `drive_devtools` / `browser_validate` | dalfox、xsstrike |
| 竞态 | `race_test` | — |
| WAF 绕过 | `waf_bypass`、`bypass_lookup` | smuggler |
| OOB（SSRF/XXE/盲 RCE） | `oob_start`（**注意：默认是本地监听，公网目标必须自建公网监听或 interactsh 域名**） | interactsh-client |
| 越权/IDOR | `sibling_scan` | — |
| 认证/会话 | `jwt_analyze` → `jwt_forge`、`auth_login` | jwt_tool |
| 漏洞库 | `cve_verify`、`nvd_lookup`、`cve_correlation`、`framework_intel` | nuclei |
| 发现管理 | `finding_create` → `finding_attach_evidence` → `finding_transition` | — |
| 报告 | `generate_report`、`write-report` 技能 | — |
| 证据/截图 | `screenshot`、`redact` | — |
| 工程管理 | `engagement_start`、`engagement_track`、`task_start`、`todo_list` | — |
| 字典生成 | — | cewl（从目标站点生成定制字典） |
| TLS | `tls-transport-security` 技能 | testssl |

## 实战教训（example-aspnet 那轮踩的）

1. **`oob_start` 在云端默认起本地监听**（如 `http://172.31.15.115:43783`），目标回连不到。公网目标的 OOB 要自己用公网机器监听，或改用 `webhook.site`（`POST /token` 拿 uuid → `GET /token/<uuid>/requests` 读记录）。
2. **`param_surface` / `active_scan` 无登录态时只能看到登录表单**。带登录态的目标要先手工登录拿 cookie，再把 cookie 喂给工具（或直接写脚本）。
3. **APK 逆向不要手抠字符串**。`apkleaks` 直接给 secrets + endpoints；Flutter（libflutter.so/libapp.so）用 `strings` 粗筛只能拿到少数，Dart 字符串可能分段/压缩。
4. **发现要边打边记**。手写报告时证据散在日志里，最后补报告很痛苦。用 `finding_create` + `finding_attach_evidence` 落库。
5. **工具用了没效果 ≠ 工具没用**。检查参数（登录态/代理/UA/超时）再下结论。
6. **「多台机器并行」先确认出口真的不同**。同机房的机器出口经常同段（NAT/同一网关），三台并行 = 一个 IP 打了三倍量，只会更快被封。开工前逐台 `ssh host 'curl -s -m 10 https://api.ipify.org'` 对一下。

## FOFA 资产测绘（么西么西自建 Worker）

blitzstrike 的 `fofa_search` 需要 `FOFA_EMAIL/FOFA_KEY`，**本机未配**；改用么西么西的 Worker：

```bash
cd /root/.hermes/cache/scratch/fofa
python fofa_cli.py channels                      # 看渠道
python fofa_cli.py search 'domain="target.com"' -n 50
```

- 鉴权：`HMAC-SHA256('testtoken123', f'{ts}:{path}:{nonce}')` → 头 `X-Timestamp/X-Nonce/X-Signature/X-User-Role: guest`
- 渠道：`official`（fofa.info，默认）/ `thirdparty`（fofoapi.com）
- 搜索返回 `[host, port, ...]` 数组；`results` 直接可用
- 频率限制：报「速度过快」或 `45012` 时 sleep 5s 重试

## 工具安装与 PATH

- 批量装：`install_all_tools(category="recon"|"web"|"api")`，26 个 recon 工具一次到位
- **坑**：`install_all_tools` 把 pip 版 `httpx`（Python 库）误判成 ProjectDiscovery httpx → 需 `go install github.com/projectdiscovery/httpx/cmd/httpx@latest` 重装，且 PATH 里 `/root/go/bin` 要在 `/usr/local/bin` 前面
- go 工具装完在 `/root/go/bin`，`.bashrc` 已加 `export PATH=/root/go/bin:/root/.local/bin:$PATH`
- pip 工具需 `--break-system-packages`（PEP 668）；`pipx` 已装（inql 用）
- 已装失败项：rustscan 需 cargo（改用 deb 包）、wpscan 需 ruby、rogue-jndi 需源码构建

## 通用前置

- **开工第一件事：验出口**。`curl -s -x http://127.0.0.1:7890 https://api.ipify.org`，再用 `--noproxy '*'` 跑一次对照：两个结果相同 = 代理没生效或节点回连本机，等于裸奔。
- **爆破/扫描/分发前都先验一次出口**；目标侧封禁层级（频率封 vs 段封 vs API 独立黑名单）的判断与 mihomo 多节点轮换见 `egress-ip-rotation` 技能。
- 所有流量过代理：`--proxy http://127.0.0.1:7890`（很多工具默认直连，会暴露真实 IP）。
- 大部分外部工具需要安装：`ensure_tool` 或 `install_all_tools`。
- `check_mcp` 先看 MCP server 状态（chrome-devtools-mcp 自动 npx 装，burp-suite-mcp 需手动加载）。
