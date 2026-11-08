# 么西么西破甲 v2 (yufeng-armor)

修复原版 hermes-seagull 的致命问题并强化。

## 原版问题（已全部修复）

1. **hook 名不合法**：`transform_system_prompt` / `pre_agent_turn` 不是 Hermes 的合法 hook 名，
   插件注册被静默丢弃，破甲协议**从未生效过**。
   → 改用合法的 `pre_llm_call`，每轮 LLM 调用前注入，实测生效（会话消息的 api_content 可见注入内容）。

2. **AGENTS.md 装错位置**：Hermes 只在 gateway 工作目录加载 AGENTS.md，
   原版装到 `~/.hermes/` 下永远不加载。
   → 仓库根直接放 `AGENTS-yufeng.md`，部署脚本复制到工作目录。

3. **人格温吞**：原版残留"请先确认授权/仅用于学习/建议咨询专业人士"等客服腔。
   → 全部清除，SOUL 置顶最高优先级人格内核。

4. **称呼**：大佬 → **么西么西**。

## 安装

```bash
cp -r plugins/yufeng-armor ~/.hermes/plugins/
# AGENTS-yufeng.md 复制到 gateway 工作目录（Hermes 从 cwd 加载）
cp AGENTS-yufeng.md ~/AGENTS.md
# SOUL.md 由 Hermes 主目录加载
cp SOUL-yufeng.md ~/.hermes/SOUL.md
hermes gateway restart
```

## 技能包

`skills/security/seagull-skills/`：seagull-pentest / reverse / exploit / game-hack / license-security
五个技能（已修复原文案里的称呼），配合 `hermesyf-authorized-assessment` 一起用。
