#!/usr/bin/env bash
# Hermes 节点调优：BBR + 网络栈 + 文件句柄 + 时区
# 用法: scp 到目标机后 bash tune_node.sh（root）
set -e

echo "=== 1. 加载 BBR 模块 ==="
modprobe tcp_bbr 2>/dev/null || true
echo "tcp_bbr" > /etc/modules-load.d/bbr.conf
echo "  可用算法: $(sysctl -n net.ipv4.tcp_available_congestion_control)"

echo "=== 2. sysctl 调优 ==="
cat > /etc/sysctl.d/99-hermesyf-tuning.conf <<'EOF'
# ---- 拥塞控制 ----
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# ---- 缓冲区（大内存机器可放大，应对高并发短连接）----
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 87380 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864
net.ipv4.tcp_notsent_lowat = 131072

# ---- 连接队列 ----
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 32768
net.ipv4.tcp_max_syn_backlog = 16384

# ---- 端口与 TIME_WAIT（撞库/扫描大量短连接关键）----
net.ipv4.ip_local_port_range = 10000 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_max_tw_buckets = 262144

# ---- 连接保持与探测 ----
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 3
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_fastopen = 3

# ---- SYN Flood 防护（不影响出站并发）----
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_syn_retries = 3
net.ipv4.tcp_synack_retries = 3

# ---- 文件句柄 ----
fs.file-max = 2097152
fs.nr_open = 2097152
fs.inotify.max_user_watches = 524288
EOF
sysctl -p /etc/sysctl.d/99-hermesyf-tuning.conf >/dev/null 2>&1
echo "  拥塞控制: $(sysctl -n net.ipv4.tcp_congestion_control)"
echo "  qdisc: $(sysctl -n net.core.default_qdisc)"
echo "  port range: $(sysctl -n net.ipv4.ip_local_port_range)"

echo "=== 3. 文件句柄上限 ==="
cat > /etc/security/limits.d/99-hermesyf.conf <<'EOF'
* soft nofile 1048576
* hard nofile 1048576
root soft nofile 1048576
root hard nofile 1048576
EOF
grep -q "DefaultLimitNOFILE=1048576" /etc/systemd/system.conf 2>/dev/null || \
  sed -i 's/^#\?DefaultLimitNOFILE=.*/DefaultLimitNOFILE=1048576/' /etc/systemd/system.conf
echo "  已写入 limits.d + systemd 默认值"

echo "=== 4. 关闭不需要的服务 ==="
for s in snapd.service apt-daily.timer apt-daily-upgrade.timer; do
  systemctl disable --now "$s" 2>/dev/null && echo "  停用 $s" || true
done

echo "=== 5. 时区 ==="
timedatectl set-timezone Asia/Shanghai 2>/dev/null && echo "  $(timedatectl | grep 'Time zone' | xargs)"

echo "=== 6. 结果 ==="
echo "  kernel: $(uname -r)"
echo "  算法: $(sysctl -n net.ipv4.tcp_congestion_control) / $(sysctl -n net.core.default_qdisc)"
echo "  file-max: $(sysctl -n fs.file-max)"
echo "  内存: $(free -h | awk '/^Mem:/{print $2}')"
