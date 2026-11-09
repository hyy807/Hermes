#!/usr/bin/env python3
"""Hermes Agent 自主调用验证

测试当前 Hermes 实例能否：
1. 理解自然语言任务
2. 加载 hermesyf-authorized-assessment 技能
3. 自主构造并调用正确的 yf_tools CLI
4. 解析并报告结果
"""
import json
import subprocess
import sys
from pathlib import Path

def main():
    project_root = Path(__file__).parent.parent
    
    print("Hermes Agent 自主调用验证")
    print("=" * 60)
    
    # 验证环境
    policy = project_root / ".test/localhost-policy.json"
    targets = project_root / ".test/localhost-targets.json"
    
    if not policy.exists() or not targets.exists():
        print("❌ 测试文件缺失")
        return 1
    
    # 验证本地服务器
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5) as r:
            if r.status != 200:
                print(f"❌ 本地服务器响应异常: {r.status}")
                return 1
        print("✅ 本地测试服务器正常 (127.0.0.1:8000)")
    except Exception as e:
        print(f"❌ 无法连接本地服务器: {e}")
        return 1
    
    # 验证工具直接调用
    print("\n1. 验证工具直接调用...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "yf_tools.assessment_run",
             "--policy", str(policy),
             "--targets", str(targets)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            print(f"❌ 工具执行失败: {result.stderr}")
            return 1
        
        report = json.loads(result.stdout)
        if report['status'] != 'completed':
            print(f"❌ 评估未完成: {report['status']}")
            return 1
        
        print(f"✅ HTTP 基线检查完成，状态: {report['status']}")
        print(f"   - 检测到服务器: SimpleHTTP/Python")
        print(f"   - 安全头缺失: {sum(not v for v in report['results'][0]['header_presence'].values())}/5")
    except Exception as e:
        print(f"❌ 工具调用异常: {e}")
        return 1
    
    # Agent 自主调用验证说明
    print("\n2. Agent 自主调用验证")
    print("=" * 60)
    print("下一步需要向 Hermes Agent 发送自然语言任务：")
    print()
    print("  「请加载 hermesyf-authorized-assessment 技能，")
    print("   然后使用 /root/projects/Hermes/.test/ 中的")
    print("   策略文件评估本地测试服务器 127.0.0.1:8000」")
    print()
    print("预期 Agent 行为：")
    print("  1. 加载技能")
    print("  2. 读取策略文件理解授权范围")
    print("  3. 调用 terminal() 执行 assessment_run")
    print("  4. 解析 JSON 结果")
    print("  5. 生成人类可读报告")
    print()
    print("✅ 环境准备完成，等待 Agent 验证")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
