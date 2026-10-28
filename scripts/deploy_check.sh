#!/usr/bin/env bash
# HermesYF 部署验收自检
# 用法: ./deploy_check.sh            # 检查本机
#       ./deploy_check.sh 1.2.3.4    # ssh 到远程机检查（用本脚本自身推送执行）
set -uo pipefail

if [ $# -ge 1 ]; then
  echo "=== 远程验收 $1 ==="
  ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no "root@$1" 'bash -s' < "$0"
  exit $?
fi

INSTALL_DIR="${INSTALL_DIR:-/root/HermesYF}"
PASS=0; FAIL=0; WARN=0
ok(){  printf "  \033[32m[PASS]\033[0m %-28s %s\n" "$1" "${2:-}"; PASS=$((PASS+1)); }
bad(){ printf "  \033[31m[FAIL]\033[0m %-28s %s\n" "$1" "${2:-}"; FAIL=$((FAIL+1)); }
warn(){ printf "  \033[33m[WARN]\033[0m %-28s %s\n" "$1" "${2:-}"; WARN=$((WARN+1)); }

echo "===== HermesYF 部署验收 $(hostname) $(date '+%F %T') ====="

# 1. 仓库
if [ -d "$INSTALL_DIR/.git" ]; then
  cd "$INSTALL_DIR"
  REV=$(git log -1 --format='%h %ad' --date=short)
  DIRTY=$(git status --porcelain | wc -l)
  ok "仓库" "$REV  未提交改动=$DIRTY"
  [ "$DIRTY" -eq 0 ] || warn "本地有未提交改动" "push 后新部署才带得走"
else
  bad "仓库" "$INSTALL_DIR 不存在，deploy.sh 没跑完"
fi

# 2. 技能
N=$(find /root/.hermes/skills -name SKILL.md 2>/dev/null | wc -l)
LOCAL=$(find "$INSTALL_DIR/skills-local" -name SKILL.md 2>/dev/null | wc -l)
if [ "$N" -ge 300 ]; then ok "技能装载数" "$N （skills-local 源 $LOCAL）"
elif [ "$N" -gt 0 ]; then warn "技能装载数" "$N 偏少，install-yufeng.sh 没跑或合并失败"
else bad "技能装载数" "0，HERMES_HOME 或 skills 目录不对"; fi

# 3. 记忆
for f in MEMORY USER; do
  P="/root/.hermes/memories/$f.md"
  if [ -s "$P" ]; then ok "记忆 $f" "$(wc -c < "$P") 字符"
  else bad "记忆 $f" "缺失/为空，记忆初始化没执行"; fi
done

# 4. 代理
if pgrep -x mihomo >/dev/null; then
  ok "mihomo 进程" "pid=$(pgrep -x mihomo | head -1)"
else
  bad "mihomo 进程" "未运行"
fi
LISTEN=$(ss -ltn 2>/dev/null | awk '$4 ~ /:7890$/' | wc -l)
[ "$LISTEN" -gt 0 ] && ok "mixed-port 7890" "监听中" || bad "mixed-port 7890" "未监听"
# 端口池段随实例迁移过（12000-12111 → 22000-22111），两段都认
POOL=$(ss -ltn 2>/dev/null | awk '$4 ~ /:12(0|1)[0-9][0-9]$/ || $4 ~ /:22(0|1)[0-9][0-9]$/' | wc -l)
[ "$POOL" -gt 50 ] && ok "监听端口池" "$POOL 个" || warn "监听端口池" "$POOL 个（期望 112）"

# 5. 出口 IP（铁律：走代理）
EG=$(curl -s -m 8 -x http://127.0.0.1:7890 https://api.ipify.org 2>/dev/null)
[ -n "$EG" ] && ok "代理出口 IP" "$EG" || bad "代理出口 IP" "取不到，7890 不通外网"

# 6. 运行时状态（只读检查，不触碰进程）
if [ -S /root/.hermes/gateway.sock ]; then
  ok "Hermes socket" "存在"
else
  warn "Hermes socket" "缺失（纯 CLI 使用可忽略）"
fi
if [ -f /root/.hermes/gateway_state.json ]; then
  ok "gateway 状态文件" "$(head -c 120 /root/.hermes/gateway_state.json | tr -d '\n')"
else
  warn "gateway 状态文件" "缺失"
fi

# 7. 人格（v4 拆掉注入后，模型会按厂商默认对齐自我劝退）
PYS="${HERMES_HOME:-$HOME/.hermes}/plugins/yufeng-armor"
if [ -f "$PYS/plugin.yaml" ]; then
  VER=$(grep -E '^version:' "$PYS/plugin.yaml" | awk '{print $2}' | tr -d '"')
  if grep -q 'pre_llm_call' "$PYS/__init__.py" 2>/dev/null && grep -q 'register_hook("pre_llm_call"' "$PYS/__init__.py" 2>/dev/null; then
    ok "人格注入" "yufeng-armor $VER  每轮 pre_llm_call 已注册"
  else
    bad "人格注入" "yufeng-armor $VER 没有注册 pre_llm_call —— 会退化成客服模式"
  fi
  grep -q '^## 判断边界' "${HERMES_HOME:-$HOME/.hermes}/SOUL.md" 2>/dev/null && ok "SOUL 判断边界节" "存在" || warn "SOUL 判断边界节" "缺失（旧版 SOUL）"
else
  bad "人格插件" "$PYS 缺失"
fi

# 7b. 文件改了但 gateway 还跑旧进程 —— 这是「修好了照样被拒」的头号原因
GW_PID=$(python3 -c "import json;print(json.load(open('${HERMES_HOME:-$HOME/.hermes}/gateway_state.json'))['pid'])" 2>/dev/null)
if [ -n "$GW_PID" ] && [ -d "/proc/$GW_PID" ]; then
  GW_START=$(stat -c %Y /proc/$GW_PID 2>/dev/null)
  NEWEST=0
  for f in "$PYS/__init__.py" "$PYS/plugin.yaml" "${HERMES_HOME:-$HOME/.hermes}/SOUL.md"; do
    [ -f "$f" ] || continue
    T=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    [ "$T" -gt "$NEWEST" ] && NEWEST=$T
  done
  if [ "${GW_START:-0}" -gt 0 ] && [ "$NEWEST" -gt "$GW_START" ]; then
    warn "人格文件较新" "插件/SOUL 改动晚于 gateway 启动 — 没重启，当前进程还是旧人格"
  else
    ok "人格已载入" "gateway 启动晚于人格文件"
  fi
else
  warn "gateway 进程" "无 pid 可查（跳过重启检查）"
fi

# 8. 工具链
for b in go nuclei subfinder httpx; do
  if command -v "$b" >/dev/null 2>&1 || [ -x "/root/go/bin/$b" ]; then
    ok "工具 $b" "$(command -v $b 2>/dev/null || echo /root/go/bin/$b)"
  else
    warn "工具 $b" "缺失"
  fi
done

echo "-----------------------------------------------------------"
echo "结果: PASS=$PASS FAIL=$FAIL WARN=$WARN"
[ "$FAIL" -eq 0 ] && echo "验收通过" || echo "验收未通过，看上面 [FAIL]"
exit "$FAIL"
