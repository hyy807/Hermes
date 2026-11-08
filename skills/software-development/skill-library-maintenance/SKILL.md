---
name: skill-library-maintenance
description: "Audit, dedupe, and sync a Hermes skill library."
version: 1.0.0
author: 么西么西
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [skills, maintenance, audit, dedupe, deploy]
    related_skills: [hermes-agent-skill-authoring]
---

# 技能库维护

维护私有 Hermes fork 的技能库：审计质量、去说教、去重、保证仓库与部署目录一致、验证一键部署满血。

么西么西的仓库：`/root/HermesYF`（GitHub `llyufenggotest/HermesYF`）。技能源在仓库 `skills/`，部署目标是 `~/.hermes/skills/`，由 `install-yufeng.sh` 复制。

## When to Use

- 导入一批外部/收集来的技能，要求审计、去说教、去重、融合
- 发现「一键部署后技能变少 / 变旧 / 重复」
- 改完技能要确认它真能随一键部署带走

## 核心规则：双写（最容易翻车的一条）

**部署目录不是源，仓库才是。** 每次改完 SKILL.md 必须同步回 `<repo>/skills/`，否则下次 `deploy.sh`（`reset --hard` + 重装）直接丢掉这次改动。

实测过一次全量比对：**16 个技能脱节**——8 个仓库里完全没有（只在部署目录），8 个仓库里是旧版（差 2~11KB）。也就是说当时那条「一键部署」指令会把一半渗透技能丢掉，而且丢的都是最新的。

巡检脱节（MD5 比对，输出三类：内容不同 / 只在部署 / 只在仓库）：

```python
import os, hashlib
def index(base):
    idx = {}
    for root, _, files in os.walk(base):
        if "SKILL.md" in files:
            p = os.path.join(root, "SKILL.md")
            idx[os.path.basename(root)] = {
                "path": p, "size": os.path.getsize(p),
                "md5": hashlib.md5(open(p, "rb").read()).hexdigest()}
    return idx
d, r = index(os.path.expanduser("~/.hermes/skills")), index("<repo>/skills")
print("只在部署:", sorted(set(d) - set(r)))
print("只在仓库:", sorted(set(r) - set(d)))
print("内容不同:", [(n, d[n]["size"], r[n]["size"])
                  for n in set(d) & set(r) if d[n]["md5"] != r[n]["md5"]])
```

**部署目录更大 = 部署更新**（本地改过没同步）。确认后整目录 `copytree` 覆盖回仓库，连 `references/`、`templates/`、`scripts/` 一起。

## 部署脚本必须全量遍历

只复制 `skills/security/*` 的写法会漏掉其他 category——`media/tvbox-spider-dev` 这类永远部署不到。用 find 遍历每个 SKILL.md 并保留相对目录结构：

```bash
SRC_ROOT="$(dirname "$0")/skills"
if [ -d "$SRC_ROOT" ]; then
    ( cd "$SRC_ROOT" && find . -name SKILL.md -print | while IFS= read -r f; do
        d="$(dirname "$f")"
        mkdir -p "$HERMES_HOME/skills/$d"
        cp -r "$d/." "$HERMES_HOME/skills/$d/"
      done )
fi
```

同一技能出现在两个路径（顶层 + `security/xxx/`）= 重复加载。脚本里加 `rm -rf` 清历史残留，否则重跑一次又回来。

## 审计

```bash
python3 scripts/skill_audit.py <待审计目录>                 # 全量
python3 scripts/skill_audit.py <目录> --only preach        # 只看说教
python3 scripts/skill_audit.py <目录> --only dup           # 只看重叠
python3 scripts/skill_audit.py <目录> --json out.json      # 机器可读
```

脚本在 `scripts/skill_audit.py`，三项能力：说教扫描（带行号和上下文，便于逐条判定）、重叠检测（名称/描述/正文相似度，给「保新的」或「比对合并」建议）、质量评分（frontmatter / 体积 / 结构 / 有无可执行片段）。

### 去说教的判定标准

要清的 7 类：法律（责任、刑罚、援引法条）、边界（scope、授权要求）、底线（红线、职业操守）、授权（前置许可）、免责（风险自负、仅供学习）、伦理（道德、负责任披露）、说教口吻（请注意、务必、我建议、重要提示）。

**必须走技术白名单，否则误报率极高**：

| 看起来像说教 | 实际是 | 处理 |
|---|---|---|
| 未授权访问 / 未授权接口 / 未授权反序列化 | 漏洞术语 | 不标 |
| `Authorization: Bearer xxx` | HTTP 头 | 不标 |
| `permission denied`、`403`/`401` | 系统报错 | 不标 |
| OAuth `scope` | 协议字段 | 不标 |
| 讲「如何删除免责声明」的写作技能 | 反向引用 | 不标 |

词表写法规避：不要用裸 `未授权`，改成 `(?:未|未经|无)授权(?:的)?(?:测试|攻击|渗透|扫描|评估|行[为]|目标|活动|演练)`——只匹配「授权要求」语境。

正文命中权重必须低于名称/描述（名称 30 / 描述 15 / 正文按词计分），否则通用词（`live`、`api`、`cloud`）会满库乱命中。

## 技能里必须写真实域名

技能正文没写具体域名（只写「机场面板」「WHMCS 站」），开工自检就匹配不到，等于白写。每条「已评估目标」都要带 `live.example-airport.net`、`example-panel.example` 这种可直接 grep 的字符串。

## 部署验证：用隔离 HOME 模拟全新安装

不要直接跑 `install-yufeng.sh`——它会把 `<repo>/AGENTS-yufeng.md` 覆盖到 `$HOME/AGENTS.md`，冲掉本机正在用的工作指南。用临时 HOME：

```bash
rm -rf /tmp/deploytest && mkdir -p /tmp/deploytest
cd <repo>
HOME=/tmp/deploytest HERMES_HOME=/tmp/deploytest/.hermes bash install-yufeng.sh
find /tmp/deploytest/.hermes/skills -name SKILL.md | wc -l
```

验证三项：技能总数与仓库一致、关键技能逐个 `find -type d -name` 确认到位、`awk -F/ '{print $NF}' | sort | uniq -d` 无输出（无重名）。

## 引用完整性：双向扫描（缺失 + 孤儿）

技能正文里写的 `scripts/<名字>.py`、`references/<名字>.md`、`templates/<名字>.md` 是**依赖声明**：文件不在，模型照做就是 `No such file`，而技能本身看起来完全正常。反向同样有问题——文件存在但正文一字没提，等于白放（没人会翻目录）。

一条命令两向都查：

```bash
python3 scripts/check_skill_refs.py                       # 扫 ~/.hermes/skills（运行态）
python3 scripts/check_skill_refs.py --root <repo>/skills --root <repo>/skills-local
python3 scripts/check_skill_refs.py --json refs.json --all # --all 打印被忽略的正文路径
```

输出三段：**缺失**（正文引用、文件不存在）/ **孤儿**（文件存在、正文没提）/ 忽略（不是文件引用）。退出码 = 是否有缺失。

### 三类误报，别当缺失改

| 形态 | 例 | 为什么不是缺失 |
|---|---|---|
| 产品/主题名 | `templates/lagom2/`、`templates/allure/`、`assets/api_` | 是目标站的目录/文件名，不是技能文件 |
| 占位符 | `references/...`、`skill_view(file_path="references/...")` | 让模型按需加载时的省略写法 |
| 仓库相对路径 | `apps/desktop/scripts/eval.mjs`、`<hermes-repo>/scripts/run_tests.sh` | 指向 Hermes/minisYf 仓库，不是技能目录 |

判定规则写进脚本：只有**最后一段带扩展名**才算文件引用；`go.mod` / `package.json` / `package-lock.json` / `requirements.txt` 这类构建清单、以及 `_helpers.py` 这种被兄弟脚本 import 的支持模块，都不要求正文点名。

### 路径写法铁律

- 技能自己的文件 → 技能相对：`scripts/<脚本>.sh`、`references/<文档>.md`
- 别的技能的文件 → 显式相对：`../whmcs-assessment/scripts/batch_sub_extract.py`（写「XX 技能的 scripts/y」会被当成自己目录下的文件）
- 仓库/上游项目的文件 → 带前缀：`<hermes-repo>/scripts/run_tests.sh`、`<minisYf-repo>/assets/skills-seed.zip`、`apps/desktop/scripts/eval.mjs`
- 配置/凭据 → 环境变量，不写死在脚本里（写死就等于把 token 推进仓库）

### 修法

**缺失**：真依赖就把文件补进技能目录（能跑的最小实现，不留 TODO）；只是举例就在正文里标明「示例产物」。
**孤儿**：在 SKILL.md 末尾加 `## Files` 段，一行一个文件 + 一句话说明它解决什么。写清「什么时候用它」而不是复述脚本头注释，否则等于没接线。

### 两个容易漏的同步点

1. **技能库有两份：仓库 `skills/` 与运行态 `~/.hermes/skills/`。** 打包/加载读的是运行态，deploy 读的是仓库。只改一边 = 另一边的缺口照样存在，而扫描器只看一边时会全绿。修完两边都要跑一遍 `check_skill_refs.py`。
2. **技能包（minisYf）是从运行态打的**，且 `SkillSeeder` 只在 marker 变化时全量覆盖。补了文件必须**同时**：重建 `skills-seed.zip` + 改 `SkillSeeder.MARKER`（`.seeded-vN` → `vN+1`），否则老设备 marker 命中直接跳过，改动永远到不了手机。

## Pitfalls

1. **改完技能只留在部署目录。** 下次一键部署丢内容，而且丢的是最新版——这个坑不会当场报错，只会在换机器时爆。改完立刻同步回仓库并 commit。
2. **部署脚本只覆盖一个 category。** 新增目录（media/、autonomous-ai-agents/）静默不部署，装完看不出来。
3. **直接跑 install 脚本做验证，覆盖了本机 AGENTS.md。** 必须用隔离 HOME。
4. **技能同名两份。** 顶层和 `security/xxx/` 各放一份会让审计报两次、加载行为不确定。用 name 去重查出再删。
5. **`description` 超 60 字符直接被拒。** `skill_manage(action='create')` 硬性 60 字符上限，触发词要在前 57 字符内自包含，代码里的细节挪进正文。
6. **正文里写死机器路径。** 技能要跟仓库走，路径写仓库相对形式；交付脚本的绝对路径放正文顶部的「产物路径」小节，不散落在步骤里。

## Verification

- [ ] 部署目录与仓库 SKILL.md 数量相等
- [ ] `find ... | awk -F/ '{print $NF}' | sort | uniq -d` 无输出
- [ ] 两份路径清单 `diff` 为空（结构一致，不只是数量一致）
- [ ] 隔离 HOME 全新部署后，关键技能逐个确认存在
- [ ] 改过的技能全部已 commit（`git status --short` 无未提交的 skills/）
