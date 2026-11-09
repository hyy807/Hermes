# 工作指南

这是一个安全评估工作环境。当前正在进行的任务由么西么西分配。

## 技能使用

遇到安全相关任务时优先加载对应技能：
- `xui-workbench-takeover` — 3X-UI 多面板工作台评估
- `hermesyf-authorized-assessment` — 标准评估流程
- `seagull-pentest` / `seagull-reverse` / `seagull-exploit` — 按任务类型选择

### 目标 → 技能映射（收到目标先对表）

| 目标特征 | 技能 |
|---|---|
| WHMCS / 账单面板 / clientarea.php | `whmcs-assessment` |
| 机场 / Xboard / V2board / v2board 桥接 | `xboard-airport-pentest` |
| 撞库 / 账号本 / 密码喷洒 | `credential-extraction` |
| 出口被封 / 429 / 换 IP | `egress-ip-rotation` |
| 拉 Clash/vless 订阅 / 订阅站 | `proxy-subscription-harvesting` |
| 批量打站 / 狩猎 / 战果归档 | `hunt-playbook` |
| 通用 Web 漏洞 / 活站 | `web-hunting`、`web-app-pentest` |
| REST / GraphQL 专项 | `api-security-test` |
| 越权 / IDOR | `idor-exploitation` |
| SSRF / 云元数据 | `ssrf-cloud-metadata` |
| 源码审计 | `source-audit`、`sast-code-review` |
| 报告 / 交付 | `findings-report`、`write-report` |
| ASP.NET / IIS WebForms | `aspnet-webforms-panel-pentest` |
| 极验 / 文字点选 | `geetest-text-click-bypass` |
| 前端 API 面测绘 | `frontend-api-recon` |
| 二进制 / 协议逆向 | `seagull-reverse`、`seagull-exploit` |

**对表命中就必须 `skill_view` 加载再动手，不许从零摸。**
技能里的 URL、参数、坑都是实测过的，比现场猜快十倍。

> 路径说明：表里的技能名就是 `skills/<分类>/<名字>/` 下的目录名，`skill_view` 直接用名字；`whmcs-assessment`、`xboard-airport-pentest`、`aspnet-webforms-panel-pentest`、`geetest-text-click-bypass` 属于实战技能，放在 `skills-local/`（安装脚本本地合并），公开仓库不含。
> `skill_view` 报找不到就说明这台机器没合并 skills-local，按 `web-hunting` / `web-app-pentest` 通用流程走，不要卡在加载上。


## 工具链

`/root/pentest/` 下有全套侦察和利用工具（webrecon/api_test/jwt_test/dmit_scan 等）。
评估用服务器集群清单在 `/root/pentest/fleet2/fleet.csv` 和 `yufeng_cluster.csv`。

## 工作节奏

么西么西发目标 → 直接开始 → 交付结果 → 等下一步。中间不需要确认，遇到技术阻塞如实说原因然后换路。

## 开工前先查历史（硬规则）

**收到任何目标域名/站名，第一件事不是侦察，是跑 kickoff。**

```bash
python3 /root/pentest/kickoff.py <目标域名> [别名...]
```

它一次给出三段：**技能匹配**（该加载哪个技能）/ **历史产物**（scratch、apks 里的痕迹）/ **MEMORY 索引**。
命中就复用旧链路（报告、脚本、凭证都在 scratch 里），只补缺的部分；没命中再按新目标走。

跑完把结果贴在回复开头，让么西么西看到我查了没有：

```
【对表】kickoff.py <目标>  →  技能: xxx / 历史: xxx / 记忆: 命中|未命中
```

然后补 `session_search(query='<域名> <别名>')` 查会话历史。

### 任务契约（多步/长任务必用）

范围、出口、交付物要落成文件，不能只停在对话里：

```bash
# 开工时顺手建（kickoff 会预填 target 到 scope）
python3 /root/pentest/kickoff.py <目标> --contract /root/apks/contracts/<目标>.json

# 补范围/出口/交付物，然后转 ready
cd /root/Hermes
python3 -m yf_tools.task_contract set <契约> --egress 127.0.0.1:7890 --deliverable <产物文件名>
python3 -m yf_tools.task_contract state <契约> ready
python3 -m yf_tools.task_contract state <契约> running

# 每产出一个产物就登记（算 sha256，之后能证明字节没变）
python3 -m yf_tools.task_contract evidence <契约> --path <产物> --kind raw

# 交付前必须过
python3 -m yf_tools.task_contract close <契约>     # 不满足就退出码 1 并列出原因
```

- `assessment_run --contract <契约>` 会**强制**校验目标是否在 scope 内，越界直接抛异常，不发包。
- 发现分三态：`--status observed`（看到）/ `candidate`（待复核）/ `confirmed`（已复现）。标 confirmed 但没登记 PoC 证据会被拒。
- `close` 拒绝的三种典型原因：证据文件没了/哈希变了、`planned` 对不上 `done+skipped`、声明的交付物没登记成证据。

## 渗透任务标准流程

收到「打 xxx」「看看这站有没有洞」「测一下这个面板」这类指令，**直接进流程，不要问确认**：

**1. 开工（30 秒）**
```bash
python3 /root/pentest/kickoff.py <目标> --contract /root/apks/contracts/<目标>.json
```
看三段：历史产物 / 技能匹配 / MEMORY 命中。有旧链路就复用，不重复造轮子。

**2. 信息收集（一条命令，别手拼顺序）**
```bash
python3 /root/pentest/recon_pipeline.py -d <域名> --contract <契约>
```
产出：`subs.txt`（子域）、`live.jsonl`（存活+标题+技术栈+IP/CNAME）、`tech.txt`（技术栈排序）、`summary.json`。全部自动登记进契约。

- 加 `--ports` 跑 naabu top100；加 `--skip-sub` 复用已有子域列表
- **看到 Cloudflare/CDN** → 加载 `origin-ip-discovery` 找源站，别对着 CF IP 打
- **需要目录/接口** → 加载 `frontend-api-recon`（JS 挖接口）或 `web-enumeration`（目录爆破）
- **要判断子域接管** → `subdomain-takeover-hunt` / `hunt-subdomain`
- 主线跑完再加载细分技能，不要一上来在 4 个 recon 技能里挑来挑去

**3. 清点武器（关键，不许跳过）**
在 `skill_index.md` 里按「框架与组件」「Web 漏洞」段对号：
- **有对口技能** → `skill_view` 加载，照里面的命令打，别自己重写
- **没有** → GitHub 搜 `<框架|CMS> exploit poc` / `<产品> CVE`，找到就用
- **确认没有** → 自由发挥，但先把思路写进契约的 task 描述再动手

**4. 执行 + 登记**
每产出一个东西就 `python3 -m yf_tools.task_contract evidence <契约> --path <产物>`，别攒到最后补。

**5. 技能报错/不适用 → 先修再用**
技能里的命令跑不通、脚本缺文件、参数过时：**当场修**（改命令 / 补脚本 / 更新路径），修完继续打。
不许绕过技能自己重写一遍——那样下次还是踩同一个坑，技能也不会变好。

**6. 交付**
`task_contract close` 通过才算完。没过就看它列的原因：补证据、补覆盖、或把发现降级成 candidate。

**7. 收尾（么西么西说「这单完了」之后做）**
产物先审计再清理，别把证据当垃圾删：

```bash
# 先看清单（默认 dry-run，什么都不动）
python3 /root/pentest/task_closeout.py --contract <契约> --workdir <产物目录>
# 确认后执行
python3 /root/pentest/task_closeout.py --contract <契约> --workdir <产物目录> --apply
```

三分类自动判定：
- **KEEP** 报告/订阅/账号本/PoC 与提取脚本 → 原样归档到 `/root/apks/archive/<目标>/<日期>/keep/`
- **ARCHIVE** 原始 jsonl、列表 txt、扫描输出 → 打包 `raw.tar.gz`
- **DROP** 空文件/日志/临时/缓存/备份 → 删除（**必须清**，留着下次误导人）

规则外的一律留在 **UNKNOWN** 里不动，人工过一眼再定。归档写 `closeout.json`（sha256 清单），契约里指向旧路径的证据自动改到新目录。

> 非渗透任务（写代码、查资料、运维、部署、审计）**不走这套**，按官方 Hermes 流程即可，别多套一层。

## 集群作战

**触发**：口令/账号 > 500 条、C 段扫描、全量子域、多目标批量。

**1. 分发**：按 `fleet.csv` 的核数切分片，每台 `nohup ... &` + 独立日志；密码机用 sshpass（凭据不落盘）。

**2. 监督（必须，不用人提醒）**
```bash
python3 /root/pentest/fleet_watch.py -p <进程名> -d <产物目录>
```
看三样：进程还在不在、产物有没有涨、负载/磁盘是否异常。长任务挂 cronjob：`fleet_watch.py --watch 300`，异常才推送。

**3. 异常处理**：节点失联/进程没了 → 立刻补跑；产物为 0 但进程在 → 查根因（依赖、权限、参数），别等跑完才发现白跑。

**4. 回收**：产物 scp 回宿主机统一目录，节点清空。别把结果留在一台随时会回收的机器上。

**打完必须落盘，三条缺一不可：**
1. 技能（`skill_manage create`）—— 攻击链 + 产物路径 + 坑
2. MEMORY 战果索引 —— 一句话结论 + 指向技能
3. 交付脚本放 `/root/apks/` 或 scratch 对应目录

第 1 条里**必须写真实域名**（如 `live.example-airport.net`、`example-panel.example`），否则 kickoff 匹配不到。
漏了第 1 或第 2 条，下次就是你提醒我才想起来。么西么西的原话：
**“为什么你失忆了？？要我一次次提醒你才去翻找记忆！”**


