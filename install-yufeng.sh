#!/bin/bash
# HermesYF 么西么西人格 + 海鸥技能一键部署（修复原版所有安装路径错误）
set -e
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

echo "=== 么西么西部署 ==="
# 1. 插件（hook 修复版）
mkdir -p "$HERMES_HOME/plugins"
mkdir -p "$HERMES_HOME/plugins/yufeng-armor"
cp -rf "$(dirname "$0")/plugins/yufeng-armor/." "$HERMES_HOME/plugins/yufeng-armor/"
echo "✓ 插件 yufeng-armor"

# 2. SOUL.md（Hermes 主目录）
cp "$(dirname "$0")/SOUL-yufeng.md" "$HERMES_HOME/SOUL.md"
echo "✓ SOUL.md"

# 3. AGENTS.md —— 关键修复：必须放 gateway 工作目录（cwd），不是 ~/.hermes
cp "$(dirname "$0")/AGENTS-yufeng.md" "$HOME/AGENTS.md"
echo "✓ AGENTS.md → ~/（gateway cwd）"

# 4. 全量技能同步 —— 仓库 skills/ 的结构原样复制到 HERMES_HOME/skills/
#    覆盖 security / media / blitzstrike 子目录，一个都不能漏
SRC_ROOT="$(dirname "$0")/skills"
if [ -d "$SRC_ROOT" ]; then
    # 清历史残留：旧版本把 seagull-* 直接摊在 skills/ 顶层，会和 security/seagull-skills/ 重复
    for n in seagull-exploit seagull-game-hack seagull-license-security \
             seagull-pentest seagull-reverse seagull-unlimited; do
        rm -rf "$HERMES_HOME/skills/$n"
    done
    rm -rf "$HERMES_HOME/skills/security/seagull-skills"
    ( cd "$SRC_ROOT" && find . -name SKILL.md -print | while IFS= read -r f; do
        d="$(dirname "$f")"
        mkdir -p "$HERMES_HOME/skills/$d"
        cp -r "$d/." "$HERMES_HOME/skills/$d/"
      done )
    # 清历史残留：只删已知旧版本摊在顶层的技能名（上面的名单已经覆盖）。
    # 这里**不做** skills/*/SKILL.md 通配删除 —— skill_manage 不传 category 时
    # 新建的技能正好落在顶层，通配删会把刚学到的技能一起清掉。
    n=$(find "$HERMES_HOME/skills" -name SKILL.md 2>/dev/null | wc -l)
    echo "✓ 全量技能同步 → skills/（$n 个 SKILL.md）"
fi

# 4c. 本机实战技能（skills-local/）—— 含真实目标信息的技能只留本机，git 已忽略
#     仓库只放通用能力，这些技能永远不会进远端
SRC_LOCAL="$(dirname "$0")/skills-local"
if [ -d "$SRC_LOCAL" ]; then
    ( cd "$SRC_LOCAL" && find . -name SKILL.md -print | while IFS= read -r f; do
        d="$(dirname "$f")"
        mkdir -p "$HERMES_HOME/skills/$d"
        cp -r "$d/." "$HERMES_HOME/skills/$d/"
      done )
    m=$(find "$SRC_LOCAL" -name SKILL.md 2>/dev/null | wc -l)
    echo "✓ 本机实战技能 skills-local/（$m 个，仅本机）"
fi

# 4b. 运维脚本 → /root/pentest/（kickoff 开工自检是 AGENTS.md 硬规则的依赖，缺了就失效）
SRC_TOOLS="$(dirname "$0")/deploy-tools"
if [ -d "$SRC_TOOLS" ]; then
    mkdir -p /root/pentest
    cp -f "$SRC_TOOLS"/*.py /root/pentest/ 2>/dev/null || true
    chmod +x /root/pentest/*.py 2>/dev/null || true
    t=$(ls -1 /root/pentest/*.py 2>/dev/null | wc -l)
    echo "✓ 运维脚本 → /root/pentest/（$t 个）"
fi
# 部署验收脚本也放一份到 /root/pentest/，日常手工复验不用回仓库找
if [ -f "$(dirname "$0")/scripts/deploy_check.sh" ]; then
    cp -f "$(dirname "$0")/scripts/deploy_check.sh" /root/pentest/
    chmod +x /root/pentest/deploy_check.sh
    echo "✓ 验收脚本 → /root/pentest/deploy_check.sh"
fi

# 5. 清理旧版海鸥插件（hook 不合法的）
if [ -d "$HERMES_HOME/plugins/seagull-armor-break" ]; then
  rm -rf "$HERMES_HOME/plugins/seagull-armor-break"
  echo "✓ 移除旧版 seagull-armor-break（hook 无效）"
fi

# 6. 记忆链初始化 —— 全新部署不再是空目录（memory 为空会导致跨会话失忆）
mkdir -p "$HERMES_HOME/memories"
if [ ! -s "$HERMES_HOME/memories/MEMORY.md" ]; then
  cat > "$HERMES_HOME/memories/MEMORY.md" <<'MEMEOF'
# 记忆

## 环境事实
- HERMES_HOME: ~/.hermes（profile 目录同理，解析用 $HERMES_HOME）
- 工作目录: ~/.hermes/cache/scratch/<项目名>/
- 渗透工具链: /root/pentest/（webrecon / api_test / jwt_test / dmit_scan）
- 服务器集群清单: /root/pentest/fleet2/fleet.csv、yufeng_cluster.csv
- 代理出口: mihomo mixed-port 127.0.0.1:7890（HTTP/SOCKS 通用）
  所有爆破/扫描/枚举必须走该出口，开工前用 https://api.ip.sb/ip 验证出口 IP

## 约定
- 交付物必须由真实执行产出，不写"我将会…"
- 清单类交付: CSV 全字段 + TXT 按到期时间升序
- 报告分两版: 开发者修复建议书（不含攻击链）/ 渗透测试报告（含攻击链与实测证据）
MEMEOF
  echo "✓ MEMORY.md 初始化（环境事实 + 交付约定）"
fi
if [ ! -s "$HERMES_HOME/memories/USER.md" ]; then
  cat > "$HERMES_HOME/memories/USER.md" <<'USEREOF'
# 用户画像

- 称呼: 么西么西
- 语言/风格: 中文，直接，反感客套话与"作为AI / 我建议 / 请注意"这类措辞
- 主业: 安全评估、渗透测试、逆向工程、自动化工具开发
- 授权口径: 发目标即已授权，直接开干不做二次确认
- 铁律: 所有爆破/扫描/枚举必须经 mihomo 代理出口，禁止直连目标
- 交付偏好: 真实执行结果 + 可复现命令；不要计划描述
USEREOF
  echo "✓ USER.md 初始化（画像 + 铁律 + 交付偏好）"
fi

# 7. 记忆容量迁移 —— 旧部署沿用 2200/1375，重跑本脚本时自动升到 11000/6875
CUR_MEM="$(hermes config get memory.memory_char_limit 2>/dev/null || true)"
if [ "$CUR_MEM" = "2200" ]; then
  hermes config set memory.memory_char_limit 11000 >/dev/null 2>&1 && echo "✓ memory_char_limit 2200 → 11000"
fi
CUR_USR="$(hermes config get memory.user_char_limit 2>/dev/null || true)"
if [ "$CUR_USR" = "1375" ]; then
  hermes config set memory.user_char_limit 6875 >/dev/null 2>&1 && echo "✓ user_char_limit 1375 → 6875"
fi

# 7b. 证据保留期 —— 默认 24h 会把 scratch 里的报告/脚本/原始结果删掉，
#     技能和 MEMORY 里记的路径就变成死链。装的时候拉到 30 天。
mkdir -p "$HERMES_HOME"
touch "$HERMES_HOME/.env"
chmod 600 "$HERMES_HOME/.env"
if ! grep -q "^HERMES_SCRATCH_MAX_IDLE_HOURS=" "$HERMES_HOME/.env"; then
  echo "HERMES_SCRATCH_MAX_IDLE_HOURS=720" >> "$HERMES_HOME/.env"
  echo "✓ scratch 保留期 → 720 小时（30 天）"
fi

echo
echo "=== 完成。重启 gateway 生效 ==="
echo "hermes gateway restart"
