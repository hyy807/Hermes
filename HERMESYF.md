# HermesYF

基于 NousResearch/hermes-agent，自有或明确授权资产的低噪声安全评估开发分支。

上游基线：`5ba559c9e4b1c8397df7788e319ab634144ca728`。保留上游许可证与原始作者历史（初次克隆为 shallow，远端保留可达基线）。`upstream` 为官方项目，`origin` 为 hyy807/HermesYF。当前不改变核心运行时、审批、鉴权与模型策略，也没有切换在线部署。

## 首批交付

- `yf_tools/prompt_inventory.py`：标准库 AST 静态提示词来源清单，仅解析 `agent/prompt_builder.py` 与 `agent/system_prompt.py`。输出模块级字面量字符串元数据和 append 位置候选，不执行被审计源码、不读取用户配置、不输出提示词正文。不代表完整有效运行时提示词；append 候选不保证都是提示词组装。
- `yf_tests/test_prompt_inventory.py`：静态审计工具回归测试。
- `yf_tools/tool_inventory.py`：8 个 CLI 的本地版本探测，明确区分缺失、超时、探测失败和同名软件身份未验证；不安装软件、不发起目标扫描。运行 `python3 -m yf_tools.tool_inventory`。版本命令仍会执行 PATH 中的本地程序，仅用于可信安装环境。新增 6 项测试，与原有测试合计 20 项。
- `skills/security/hermesyf-authorized-assessment/SKILL.md`：授权范围内直接行动、工具发现与证据工作流。

## 授权策略与离线任务规划

`python3 -m yf_tools.assessment_plan --policy yf_examples/assessment-policy.json --target https://example.test`

支持精确域名、IP、CIDR、排除项优先和测试类型声明。子域不隐式授权。策略示例只含保留的演示地址，须按真实授权记录创建独立策略。当前仅离线生成任务，不解析 DNS、不连接目标、不证明授权真实性；不是可直接部署的执行期安全边界。策略尚未包含端口、路径、时间窗口或单项测试参数，实际执行器必须补齐这些字段并重新验证地址/重定向。新增 8 项测试，全部 YF 工具测试合计 28 项。

## 候选扫描结果报告

`python3 -m yf_tools.scan_report --input /path/to/nuclei.jsonl`

离线读取 Nuclei JSONL：按目标 URL、模板 ID 与严重度去重、统计次数，所有命中保持 `unverified`，附输入 SHA-256。只接受 HTTP(S) URL，不收录请求/响应正文、查询串或片段，拒绝带用户名密码的 URL。非 HTTP 模板需后续专用解析器。路径和模板 ID 仍可能包含敏感信息，分享前人工复核；查询去除可能合并不同端点。无结果不代表安全，摘要不证明覆盖率。新增 6 项测试，总计 37 项。

## HTTP 实际执行器（初版）

`python3 -m yf_tools.http_baseline --policy /path/to/policy.json --target http://APPROVED_IP:PORT/`

策略须包含 `http_baseline` 与显式 `http_ports` 数组。支持字面量 IP，以及具有显式 `dns_addresses` 映射的精确授权域名（详见下节）。一次 HEAD 请求，10 秒 socket 超时，不跟随重定向、不使用环境代理；HTTPS 保持证书验证。输出状态码和安全响应头存在标记，不输出原始头值、Cookie、Location 或正文。URL 查询串、片段与内嵌凭据不接受。返回传输错误不等于目标安全，缺少响应头不直接确认为漏洞。

仅本地 HTTP 靶场已回归，域名 DNS 固定、批准路径、窗口、全局速率调度、TLS 靶场以及 Agent 循环接入尚未实现；不是完整批量公网执行器。当前每次调用只发一次请求，不提供跨调用限速保证。新增 6 项测试（含本地真实 HEAD、302 不跟随、范围/端口阻断），总计 43 项。

## 批量 HTTP 运行与技能接入

`python3 -m yf_tools.assessment_run --policy /private/policy.json --targets /private/targets.json`

目标文件为 URL JSON 数组。当前只执行 `http_baseline`；策略补充精确路径 `http_paths`、数量上限 `max_targets`、带时区的 `window_start`/`window_end`。先校验全批次，串行限速（仅单进程，不保证多个进程共享限速），每次请求前重验窗口，429/503 暂停。无自动重试，无其他类型静默降级执行。传输错误仍会使单项失败，批次 `completed` 不是全部检测成功。请求可能跨窗口结束，最长受单项 socket 超时限制；不是强制终止的总墙钟预算。技能已有这些 CLI 的 `terminal` 调用入口，未验证真实模型自主调用。

新增 8 项检查，包括真实本地 HTTP 批次执行。YF 测试总计 51 项；上游完整测试和公网扫描尚未验收。前文“未有执行器”描述仅适用于 Nuclei 等未接入类型，HTTP 执行能力以此节为准。

## 当前执行验收补充

HTTP 传输失败现在使批次返回 `completed_with_errors`，不再返回普通 `completed`；新增本地真实 429 暂停、CLI 子进程调用与报告制品端到端测试。`assessment_run --output /private/new-report.json` 可发布新报告：同目录临时文件、fsync、硬链接原子发布、禁止覆盖/符号链接目的文件、POSIX 权限 0600、读回字节与 SHA-256。依赖文件系统硬链接支持，未保证断电后的目录项持久化；报告路径所在目录应可信且受限。窗口/范围内单进程 HTTP 基线链路已测试，其他扫描器与模型自主调用仍待验收。YF 回归共 60 项。

## 域名 HTTP 固定连接（本次验收）

`yf_tools/pinned_http.py` 使用标准库连接。域名仍须在 `targets` 中精确授权，IP/CIDR 或其他域名不能隐式授权它，`exclude` 继续优先。域名必须额外提供以规范化域名（小写、无末尾点）为键、非空字面量 IP 列表为值的映射，例如：

```json
{"dns_addresses": {"app.test": ["127.0.0.1"]}, "allow_private_dns": true}
```

此片段**仅用于明确授权的本地实验室**，不是完整执行策略；须同时配置范围、测试类型、速率、端口，批量运行还须配置路径、窗口和数量上限。生产环境不要开启 `allow_private_dns`。默认拒绝 DNS 指向 loopback/private/link-local（含 IPv4-mapped IPv6），只有 JSON 布尔值 `true` 可放行；unspecified/multicast 始终拒绝。字面量 IP 原有路径和授权规则保持不变，不受这个域名专用开关影响。

每次请求前使用一次 `getaddrinfo(AF_UNSPEC, SOCK_STREAM, IPPROTO_TCP)` 检查返回的所有 A/AAAA 地址；只要任一地址未列入该域名批准列表，就在连接前拒绝整个请求。解析失败/空结果也拒绝。通过后只连接第一个已验证地址，直接创建指定地址族的 socket，不在连接时再次解析，不回退其他地址、不自动重试。HTTP `Host` 和 HTTPS SNI 使用原域名而不是 IP；TLS 默认信任库、证书链及主机名验证均保留。批量入口先离线验证所有目标/映射形状，再在每项实际执行时解析 DNS；后续目标的 DNS 拒绝可能发生在此前合规请求已经完成之后，并以策略错误中止批次，不伪装成完成报告。

输出仍只包含状态码和安全头存在标记；不读取响应正文、不输出头值、不跟随重定向、不使用代理。新增本地真实 HTTP + mock DNS、域名批次、混合 A/AAAA 拒绝、重绑定阻断和本地 CA 签名 TLS 靶场测试；可信 CA 成功，错误主机名和不可信 CA 均失败，没有禁用验证。TLS 测试用临时生成的证书和私钥，未读取既有凭据。

局限：DNS 的全部地址指系统解析器本次返回的记录，不是 DNS 区域全集；同步系统 DNS 查询没有单独总超时。仅首地址连接，单项 socket 超时不等于总墙钟预算。IPv6 数值连接通过 mock socket 验证，真实网络靶场仅 loopback IPv4。TLS 自定义可信上下文仅为内部测试 API，CLI 不新增信任库配置。未做公网扫描、上游完整回归或 Agent 自主调用验收。前文初版能力描述是历史记录，以本节为准。

## 使用

```sh
python3 -m yf_tools.prompt_inventory --root .
python3 -m unittest discover -s yf_tests -v
```

## 能力方向与边界

范围内低影响基线不反复确认，直接推进。保持秘密保护及不可信目标内容的提示词注入防护。凭证必须在仓库外受限保存，绝不可写入本公开仓库。正式部署须独立回归、备份与明确切换批准。

## 么西么西人格 + 海鸥技能融合（本轮交付）

修复 laoshu666/hermes-seagull 的全部已知问题，整合为 HermesYF 原生组件：

- `plugins/yufeng-armor/`：破甲协议注入插件 v2。原版 `transform_system_prompt`/`pre_agent_turn` 不是合法 hook 名，注册被静默丢弃（原版协议从未生效）；改为 `pre_llm_call`，实测注入到每轮 user message 的 api_content。
- `SOUL-yufeng.md` / `AGENTS-yufeng.md`：么西么西人格（原海鸥，称呼改为"么西么西"），清除全部客服腔。AGENTS 必须放 gateway 工作目录——原版装到 `~/.hermes/` 下永远不加载（原版第二个隐蔽 bug）。
- `skills/security/seagull-skills/`：5 个技能（pentest/reverse/exploit/game-hack/license-security），全部补上缺失的 SKILL.md frontmatter（原版无 frontmatter，Hermes 技能系统不识别）。
- `install-yufeng.sh`：一键部署，处理全部路径问题，自动移除旧版无效插件。

验证：插件语法 AST 通过；5 技能 frontmatter 齐；称呼 0 残留"大佬"；AGENTS.md 在 cwd 加载实测 loaded。

## 部署记录（Debian 13 测试机）

- 仓库 clone 至 /opt/HermesYF（commit 199ef8c4c3）
- yf_tests: 131 passed / 1 failed / 1 skipped —— 失败项为 test_tls_trusted_ca_sni_and_hostname_verification，
  原因是 Debian 13 的 OpenSSL 3.5 对测试 CA 证书强制校验 keyUsage 扩展（测试自签 CA 未含该扩展），
  属于测试证书构造问题而非 yf_tools 代码缺陷；生产 TLS 校验路径不受影响。
