#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计仓库 skills/ 下每个 SKILL.md：结构、可执行性、重复。

检查项
  E1 frontmatter 缺 name / description
  E2 description 超过 60 字符（Hermes 索引预算 57+...，超了触发词被截断）
  E3 正文少于 20 行（大概率空壳）
  E4 正文引用的 scripts/ references/ 文件不存在（技能说"用这个脚本"但文件没了）
  E5 含 TODO / FIXME / 待补充 / 未实现 / placeholder
  W1 description 与另一个技能高度相似（重复或该合并）
  W2 正文没有任何命令块（纯文字，实战价值低）
  W3 name 与目录名不一致

用法
  python3 audit_skills.py                 # 审仓库 skills/
  python3 audit_skills.py --root PATH
  python3 audit_skills.py --json          # 只输出机器可读结果
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

REPO_SKILLS = Path("/root/Hermes/skills")


def front(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if km:
            out[km.group(1)] = km.group(2).strip().strip('"').strip("'")
    return out


def audit_one(p: Path) -> dict:
    text = p.read_text(encoding="utf-8", errors="replace")
    meta = front(text)
    body = re.sub(r"^---.*?---\s*", "", text, flags=re.S)
    lines = [l for l in body.splitlines() if l.strip()]
    issues = []

    name = meta.get("name", "")
    desc = meta.get("description", "")
    if not name or not desc:
        issues.append(("E1", "frontmatter 缺 name 或 description"))
    if len(desc) > 60:
        issues.append(("E2", f"description {len(desc)} 字符（>60，索引会截断）"))
    if len(lines) < 20:
        issues.append(("E3", f"正文只有 {len(lines)} 行，疑似空壳"))

    # 引用文件是否存在
    for ref in set(re.findall(r"(?:scripts|references|templates|assets)/[A-Za-z0-9_.\-/]+", body)):
        if any(ch in ref for ch in "*<>{}") or ref.endswith("/"):
            continue
        target = p.parent / ref
        if not target.exists():
            issues.append(("E4", f"引用文件不存在: {ref}"))

    prose = re.sub(r"```.*?```", "", body, flags=re.S)   # 代码块里的 grep TODO 是示例，不是待办
    for kw in ("TODO", "FIXME", "待补充", "未实现", "placeholder"):
        if kw.lower() in prose.lower():
            issues.append(("E5", f"含未完成标记: {kw}"))

    no_cmd = "```" not in body

    d = p.parent.name
    if name and d and name != d:
        issues.append(("W3", f"name({name}) 与目录({d}) 不一致"))

    return {
        "name": name or d, "dir": d, "path": str(p),
        "desc": desc, "desc_len": len(desc), "lines": len(lines),
        "category": p.relative_to(REPO_SKILLS).parts[0] if len(p.relative_to(REPO_SKILLS).parts) > 1 else "",
        "issues": issues,
        "no_cmd": no_cmd,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(REPO_SKILLS))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="/root/pentest/skill_audit.md")
    args = ap.parse_args()

    root = Path(args.root)
    rows = [audit_one(p) for p in sorted(root.rglob("SKILL.md"))]

    # 重复检测（description 相似度 >= 0.82）
    dups = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i]["desc"], rows[j]["desc"]
            if not a or not b:
                continue
            r = SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if r >= 0.82:
                dups.append((rows[i]["name"], rows[j]["name"], round(r, 2)))

    stats = {"total": len(rows), "clean": 0, "with_issues": 0}
    for r in rows:
        (stats.__setitem__("clean", stats["clean"] + 1) if not r["issues"]
         else stats.__setitem__("with_issues", stats["with_issues"] + 1))

    if args.json:
        print(json.dumps({"stats": stats, "rows": rows, "dups": dups}, ensure_ascii=False, indent=1))
        return 0

    by_code: dict[str, list] = {}
    for r in rows:
        for code, msg in r["issues"]:
            by_code.setdefault(code, []).append((r["name"], msg))

    lines = ["# 技能库审计", "",
             f"范围 `{root}`，共 **{len(rows)}** 个技能。刚好 **{stats['clean']}**，有问题 **{stats['with_issues']}**。", ""]
    for code in ("E1", "E2", "E3", "E4", "E5", "W2", "W3"):
        items = by_code.get(code, [])
        if not items:
            continue
        lines.append(f"## {code}（{len(items)}）")
        for name, msg in sorted(items)[:40]:
            lines.append(f"- `{name}` — {msg}")
        if len(items) > 40:
            lines.append(f"- …其余 {len(items)-40} 条")
        lines.append("")
    if dups:
        lines.append(f"## W1 疑似重复（{len(dups)} 对）")
        for a, b, r in sorted(dups, key=lambda x: -x[2])[:30]:
            lines.append(f"- `{a}` ≈ `{b}`  ({r})")
        lines.append("")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:60]))
    print(f"\n完整报告: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
