#!/usr/bin/env bash
# ============================================================================
# HermesYF 一键部署脚本 — 干净机器上一条命令完成安装
# ============================================================================
# 用法（在目标机上，root 用户）—— 公开库直接跑；若仓库改为私有，带 token：
#   curl -fsSL https://raw.githubusercontent.com/hyy807/HermesYF/main/deploy.sh | bash
#   私有库时：
#   export HERMESYF_TOKEN=ghp_xxx
#   curl -fsSL -H "Authorization: token $HERMESYF_TOKEN" \
#     https://raw.githubusercontent.com/hyy807/HermesYF/main/deploy.sh | bash
# 或先 clone 再本地跑（clone 用 token，见下）:
#   git clone https://x-access-token:$HERMESYF_TOKEN@github.com/hyy807/HermesYF.git /root/HermesYF
#   bash /root/HermesYF/deploy.sh
#
# 流程: 装 git/curl → clone 仓库到 /root/HermesYF → setup-hermes.sh
# ============================================================================
set -e

INSTALL_DIR="${INSTALL_DIR:-/root/HermesYF}"
REPO_SLUG="hyy807/HermesYF"
REPO_URL="https://github.com/${REPO_SLUG}.git"

# 私有库凭据：HERMESYF_TOKEN > GH_TOKEN > ~/.git-credentials
GH_TOKEN="${HERMESYF_TOKEN:-${GH_TOKEN:-}}"
if [ -z "$GH_TOKEN" ] && [ -f "$HOME/.git-credentials" ]; then
    GH_TOKEN=$(sed -E 's|.*://[^:]+:([^@]+)@.*|\1|' "$HOME/.git-credentials" 2>/dev/null | head -1)
fi
if [ -n "$GH_TOKEN" ]; then
    REPO_URL="https://x-access-token:${GH_TOKEN}@github.com/${REPO_SLUG}.git"
fi

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${CYAN}☤ HermesYF 一键部署${NC}"
echo ""

# 1. 依赖工具
missing=""
command -v git  >/dev/null 2>&1 || missing="git $missing"
command -v curl >/dev/null 2>&1 || missing="curl $missing"
command -v unzip >/dev/null 2>&1 || missing="unzip $missing"
command -v ca-certificates >/dev/null 2>&1 || true  # 包名检测从略，随 apt 一起装

if [ -n "$missing" ]; then
    echo -e "${CYAN}→${NC} 安装缺失工具: $missing"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    # 可选 cua-driver（computer-use）需要 X11/GUI 运行库，缺了只是该可选工具不可用
    apt-get install -y -qq $missing ca-certificates libxi6 libxtst6 libxkbcommon0 libxrender1 libxext6 libxfixes3 libxrandr2 libxcomposite1 libxdamage1
fi

# 2. 拉取仓库
if [ -d "$INSTALL_DIR/.git" ]; then
    echo -e "${GREEN}✓${NC} 仓库已存在，拉取最新..."
    cd "$INSTALL_DIR"
    git fetch origin 2>/dev/null
    git reset --hard origin/main 2>/dev/null
    git pull --ff-only origin main 2>/dev/null || true
else
    echo -e "${CYAN}→${NC} clone 仓库到 $INSTALL_DIR ..."
    # 仓库是公开的：没有 token 就直接走公开 URL；有 token 则用它（私有化后可继续用）
    rm -rf "$INSTALL_DIR"
    if ! git clone "$REPO_URL" "$INSTALL_DIR"; then
        echo -e "${RED}✗${NC} clone 失败。仓库若已改为私有，请 export HERMESYF_TOKEN=ghp_xxx 后重跑"
        exit 1
    fi
    cd "$INSTALL_DIR"
    if [ -n "$GH_TOKEN" ]; then
        # token 不留在 .git/config 里
        git remote set-url origin "https://github.com/${REPO_SLUG}.git"
        # 写凭据，后续 update.sh / git pull 不用再给
        git config --global credential.helper store
        ( umask 077; printf 'https://x-access-token:%s@github.com\n' "$GH_TOKEN" > "$HOME/.git-credentials" )
        chmod 600 "$HOME/.git-credentials"
        echo -e "${GREEN}✓${NC} 凭据已存 ~/.git-credentials（0600）"
    fi
fi

# 3. 部署
cd "$INSTALL_DIR"
echo -e "${CYAN}→${NC} 运行 setup-hermes.sh（首次 1-5 分钟）..."
bash setup-hermes.sh

# 4. 么西么西人格（SOUL.md + ~/AGENTS.md + yufeng-armor 插件 + 海鸥技能 + security 技能包）
echo -e "${CYAN}→${NC} 部署么西么西人格 + 技能包..."
if [ -f "$INSTALL_DIR/install-yufeng.sh" ]; then
    bash "$INSTALL_DIR/install-yufeng.sh"
else
    echo -e "${RED}✗${NC} install-yufeng.sh 缺失，人格未部署"
fi

# 5. Blitz Strike MCP（bun + main 分支 + build + 188 工具注册）
echo -e "${CYAN}→${NC} 部署 Blitz Strike MCP..."
if [ -f "$INSTALL_DIR/install-blitzstrike.sh" ]; then
    bash "$INSTALL_DIR/install-blitzstrike.sh"
else
    echo -e "${RED}✗${NC} install-blitzstrike.sh 缺失，MCP 未部署"
fi

echo ""
echo -e "${GREEN}✓ 部署完成！${NC}"
echo ""
if [ -f "$INSTALL_DIR/scripts/deploy_check.sh" ]; then
    echo -e "${CYAN}→ 自动验收${NC}"
    bash "$INSTALL_DIR/scripts/deploy_check.sh" || echo -e "${RED}✗ 验收有 FAIL，看上面输出${NC}"
fi
echo ""
echo "后续:"
echo "  source /root/HermesYF/activate   # 激活环境"
echo "  hermes setup                      # 配置 API keys"
echo "  hermes gateway restart            # 重启网关使么西么西人格生效"
