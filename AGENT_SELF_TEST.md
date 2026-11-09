---
agent_self_test: true
---

# Hermes Agent Self-Test

测试当前 Hermes 实例能否通过技能自主调用 Hermes 评估工具完成完整任务。

## 测试目标

验证 Agent 能够：
1. 加载 `hermesyf-authorized-assessment` 技能
2. 读取策略文件理解授权范围
3. 自主选择并调用合适的 `yf_tools` CLI
4. 解析结果并生成人类可读报告

## 测试场景

**场景 1：本地 HTTP 基线检查**
- 目标：本地测试 HTTP 服务器（127.0.0.1）
- 任务：HTTP 响应头基线检查
- 预期：Agent 调用 `assessment_run`，返回安全头存在性报告

**场景 2：本地端口扫描**
- 目标：127.0.0.1 指定端口
- 任务：TCP 服务发现
- 预期：Agent 调用 Nmap，识别开放端口和服务

## 测试步骤

1. 创建最小策略文件（仅授权 127.0.0.1 本地测试）
2. 启动本地测试 HTTP 服务器
3. 向 Agent 发送自然语言任务："评估本地测试服务器的安全基线"
4. 观察 Agent 是否：
   - 加载正确技能
   - 调用正确 CLI
   - 解析结果
   - 生成报告

## 当前限制

- 本测试需要 Hermes 代码在 `/root/projects/Hermes`
- 需要 Python 3.11+ 环境
- Nmap/Nuclei 测试需要对应工具已安装
- 不测试公网目标（安全限制）

## 验收标准

✅ Agent 成功调用至少一个 yf_tools CLI
✅ 返回结构化结果（JSON 或表格）
✅ 不手动指定完整命令行参数
✅ 根据上下文选择合适工具
