# 部署与更新

## 首次部署（干净机器）

```bash
curl -fsSL https://raw.githubusercontent.com/hyy807/Hermes/main/deploy.sh | bash
```

仓库目前是公开的，上面这条直接可用。<br>
若以后改回私有，改成带 token 的写法：

```bash
export HERMESYF_TOKEN=ghp_xxx      # 能读 Hermes 的 PAT
curl -fsSL -H "Authorization: token $HERMESYF_TOKEN" \
  https://raw.githubusercontent.com/hyy807/Hermes/main/deploy.sh | bash
```

deploy.sh 两种都支持：有 token 就用 token clone，没有就走公开 URL。凭据会写进 `~/.git-credentials`（0600），token 不会留在 `.git/config` 里，后续 `update.sh` 直接可用。

装完后：

```bash
source /root/Hermes/activate
hermes setup                    # 配 API key
hermes gateway restart
```

## 已经部署过，要更新

一条命令：

```bash
bash /root/Hermes/update.sh
```

它会：拉最新代码 → 同步人格 / 技能 / 运维脚本 → 报告技能数变化。
**不重装 Hermes 本体**，几十秒完成。

变体：

```bash
bash /root/Hermes/update.sh --mcp      # 同时重装 Blitz Strike MCP（188 工具）
bash /root/Hermes/update.sh --prune    # 完全对齐：删掉仓库里已不存在的技能
bash /root/Hermes/update.sh --prune --mcp
```

`--prune` 只清理 `skills/security`、`skills/pentest`、`skills/media` 三个仓库管理的目录，
**自己加的技能（其它目录）不会被动**。

更新完重启网关生效：

```bash
hermes gateway restart
```

## 部署后应该有什么

```
357 个技能
├── skills/security/    60   渗透流程 + 实战沉淀（blitzstrike 39 + 自建专项）
├── skills/pentest/     236  狩猎方法论 + 攻击执行（hunt-* / offensive-*）
└── skills/            其它  非渗透技能（创作、文档、研究等）

~/.hermes/SOUL.md           么西么西人格
~/AGENTS.md                 工作指南（含目标→技能映射表 + 开工自检硬规则）
~/.hermes/plugins/yufeng-armor/
~/.hermes/memories/         MEMORY.md + USER.md
/root/pentest/kickoff.py    开工自检（AGENTS.md 硬规则依赖它）
/root/pentest/preach_scan.py    说教逐行扫描
/root/pentest/skill_audit.py    技能审计（说教/重叠/质量）
```

自检：

```bash
find ~/.hermes/skills -name SKILL.md | wc -l        # 期望 351（朋友机器，不含本机实战技能）
python3 /root/pentest/kickoff.py example.com     # 应无命中（新目标）
```

## 常见问题

**技能数是 356 或 358，不是 357**
自己加过或删过技能。跑 `update.sh --prune` 对齐，或忽略（不影响使用）。

**更新后技能没变化**
`install-yufeng.sh` 是全量同步，会覆盖同名技能但不会删除。确认代码确实更新了：
`cd /root/Hermes && git log --oneline -1`

**kickoff.py 找不到**
旧版部署没有这个文件。跑一次 `bash /root/Hermes/update.sh` 就有了；
它由 `deploy-tools/` 目录提供，`install-yufeng.sh` 会复制到 `/root/pentest/`。

**想回到干净状态**
`update.sh --prune` 后再手动删掉不想要的技能目录即可。
不要删 `skills/security`、`skills/pentest`，那是核心内容。
