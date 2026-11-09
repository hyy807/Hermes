# Hermes：授权测试方向与静态提示词清单

## 目标和边界

Hermes 的方向是**有明确授权、范围约束和可复现证据的自动化测试**：先建立离线审计与行为测试，再按实际授权逐步扩展。它不是全能工具，不保证自动发现或利用所有问题，不代表已完成安全认证，也不应对未授权目标开展测试。

**当前只有一个标准库静态审计 CLI，尚未部署，也未接入 Agent、网关、模型或线上服务。** 本工具不修改上游代码，不加载配置或凭据，不发起网络请求，不执行目标 Python 代码。现有提示词中的防注入、安全边界和授权约束必须保留；本工具不会删除、替换或绕过这些保护。

## 使用

在仓库根目录运行（无需安装第三方依赖）：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m yf_tools.prompt_inventory
PYTHONDONTWRITEBYTECODE=1 python -m yf_tools.prompt_inventory --root /path/to/authorized/repository
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s yf_tests -p 'test_prompt_inventory.py' -v
```

`--root` 默认是当前工作目录；模块必须在 Python 的导入路径中。输出为确定性的 JSON，成功退出码为 0；失败为非零退出码，诊断只写 stderr，stdout 不输出部分结果。

## 静态清单契约

只读取指定根目录下两个明确的源文件：

- `agent/prompt_builder.py`
- `agent/system_prompt.py`

通过 AST 解析，不导入 Agent，不遍历其他源码，不读取 HOME、HERMES_HOME、配置或凭据。文件和目录符号链接解析后必须位于根目录内；允许指向根目录内部的链接，拒绝逃逸根目录的链接。此检查针对静态文件树，不是防御并发恶意文件替换的操作系统沙箱。

JSON 字段：

- `kind`：固定为 `static_prompt_source_inventory`。
- `runtime_effective_prompt`：固定为 `false`，不是运行时实际提示词。
- `text_constants`：两个文件中模块顶层直接赋值或带注解赋值的字符串字面量。每条只有名称、相对路径、行号、字符数和 UTF-8 SHA-256；链式赋值分别记录。相邻字面量由 Python 解析器合并；表达式拼接、f-string、字节串、函数局部赋值等不求值、不收录。
- `assembly_candidates`：只在 `system_prompt.py` 中记录直接 `.append(...)` 调用的相对路径、行号、AST 列偏移和调用名。包含条件分支内的候选位置，不追踪别名、不记录 `.extend(...)`，不证明调用一定执行或一定用于提示词。AST 列偏移按 Python 定义是 UTF-8 字节偏移。

不输出字符串正文、调用参数正文、绝对根路径或语法错误源码行。哈希和长度仍属于元数据，可能被用于已知文本比对；不能视为秘密信息的匿名化方案。字符串包含孤立代理码位时，哈希使用 UTF-8 `surrogatepass` 编码。

## 局限与后续方向

此清单不是完整数据流分析、提示词防注入检测器或漏洞扫描器。动态构建、导入来源、配置、技能、记忆和会话消息都可能影响最终提示词，本工具不解析这些输入，也不验证模型最终收到的内容。

下一阶段应在明确授权的隔离测试环境中，保留防注入保护，增加可复现行为测试、范围限制、人工审核与审计记录；这些是方向说明，不代表已经实现或部署。不得把静态清单成功等同于系统安全或授权自动获得。
