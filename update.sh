#!/usr/bin/env bash
# ============================================================================
# HermesYF 更新脚本 —— 已部署过的机器用这个，不重装 Hermes 本体
# ============================================================================
# 用法：
#   bash /root/HermesYF/update.sh              # 更新人格 + 技能 + 运维脚本
#   bash /root/HermesYF/update.sh --mcp        # 同时重装 Blitz Strike MCP
#   bash /root/HermesYF/update.sh --prune      # 完全对齐（删掉仓库里已没有的技能）
#   bash /root/HermesYF/update.sh --prune --mcp
#
# 常见场景：
#   - 风哥更新了仓库，朋友想同步 → 直接跑这个
#   - 换了台机器已有旧版 → 跑 deploy.sh 全套，或先 clone 再跑本脚本
# ============================================================================
set -e

INSTALL_DIR="${INSTALL_DIR:-/root/HermesYF}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

DO_MCP=0
DO_PRUNE=0
for a in "$@"; do
  case "$a" in
    --mcp)   DO_MCP=1 ;;
    --prune) DO_PRUNE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo -e "${RED}未知参数: $a${NC}"; exit 1 ;;
  esac
done

# ---------- 前置检查 ----------
if [ ! -d "$INSTALL_DIR/.git" ]; then
  echo -e "${RED}✗ 未找到仓库 $INSTALL_DIR${NC}"
  echo "  首次部署请跑（私有仓库要带 token）："
  echo "  export HERMESYF_TOKEN=ghp_xxx"
  echo "  curl -fsSL -H \"Authorization: token $HERMESYF_TOKEN\" https://raw.githubusercontent.com/llyufenggotest/HermesYF/main/deploy.sh | bash"
  exit 1
fi

SKILL_DIR="$HERMES_HOME/skills"
before=$(find "$SKILL_DIR" -name SKILL.md 2>/dev/null | wc -l)
old_rev=$(cd "$INSTALL_DIR" && git rev-parse --short HEAD)

# ---------- 拉最新 ----------
echo -e "${CYAN}☤ HermesYF 更新${NC}"
echo -e "${CYAN}→${NC} 拉取 origin/main ..."
cd "$INSTALL_DIR"
git fetch origin --quiet
git reset --hard origin/main --quiet
new_rev=$(git rev-parse --short HEAD)
echo -e "${GREEN}✓${NC} 代码 $old_rev → $new_rev"

# ---------- 人格 + 技能 + 运维脚本 ----------
echo -e "${CYAN}→${NC} 同步人格 / 技能 / 运维脚本 ..."
bash "$INSTALL_DIR/install-yufeng.sh"

# ---------- 可选：完全对齐 ----------
if [ "$DO_PRUNE" -eq 1 ]; then
  echo -e "${CYAN}→${NC} 对齐技能目录（清理仓库里已不存在的技能）..."
  removed=0
  # 只处理仓库管理的这四个顶层域，不动用户自建的其它目录
  for domain in security pentest media; do
    [ -d "$SKILL_DIR/$domain" ] || continue
    while IFS= read -r f; do
      rel="${f#$SKILL_DIR/}"          # 例: pentest/foo/SKILL.md
      rel_dir="$(dirname "$rel")"     # pentest/foo
      if [ ! -f "$INSTALL_DIR/skills/$rel" ]; then
        rm -rf "$SKILL_DIR/$rel_dir"
        removed=$((removed + 1))
        echo "    删除 $rel_dir"
      fi
    done < <(find "$SKILL_DIR/$domain" -name SKILL.md 2>/dev/null)
  done
  echo -e "${GREEN}✓${NC} 清理 $removed 个陈旧技能"
fi

# ---------- 可选：MCP ----------
if [ "$DO_MCP" -eq 1 ]; then
  echo -e "${CYAN}→${NC} 重装 Blitz Strike MCP ..."
  bash "$INSTALL_DIR/install-blitzstrike.sh"
fi

# ---------- 汇总 ----------
after=$(find "$SKILL_DIR" -name SKILL.md 2>/dev/null | wc -l)
echo ""
echo -e "${GREEN}✓ 更新完成${NC}"
echo "  代码   $old_rev → $new_rev"
echo "  技能   $before → $after 个"
if [ -f /root/pentest/kickoff.py ]; then
  echo "  工具   /root/pentest/kickoff.py ✓"
else
  echo -e "  工具   ${YELLOW}/root/pentest/kickoff.py 缺失${NC}"
fi
echo ""
echo "重启网关后生效（在网关外部的 shell 里执行）："
echo "  hermes gateway restart"
