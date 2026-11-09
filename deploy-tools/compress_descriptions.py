#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把超过预算的技能 description 压到 <=57 字符，保留触发词。

规则
  1. "中文触发：<词> ｜ <英文>"  →  保留 "中文触发：<词>"（触发词最值钱）
  2. "Use when <句子>"          →  保留 "Use when " + 首个分句（到 , — ( ; 为止）
  3. 其它                        →  按分句/顿号截断，末尾加 …
  4. 压完仍超长                    →  硬截 56 + …

用法
  python3 compress_descriptions.py --dry-run     # 只看会改成什么
  python3 compress_descriptions.py              # 实际写入
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path("/root/Hermes/skills")
LIMIT = 57


def compress(desc: str) -> str:
    d = desc.strip().strip('"').strip("'")

    # 1) 中文触发型
    m = re.search(r"中文触发[：:]\s*(.+?)(?:\s*[｜|]\s*|$)", d)
    if m:
        core = m.group(1).strip()
        out = "中文触发：" + core
        if len(out) <= LIMIT:
            return out
        # 触发词太长：按顿号取前几个
        parts, acc = re.split(r"[、，,]", core), ""
        for p in parts:
            cand = (acc + "、" + p) if acc else p
            if len("中文触发：" + cand) > LIMIT:
                break
            acc = cand
        return "中文触发：" + (acc or parts[0])[: LIMIT - 5] + ("…" if not acc else "")

    # 2) Use when 型
    m = re.match(r"(?i)^use when\s+(.+)$", d)
    if m:
        tail = m.group(1)
        cut = re.split(r"\s*[—,;(]|\s+-\s", tail)[0].strip().rstrip(".")
        out = "Use when " + cut
        if len(out) <= LIMIT:
            return out
        return out[: LIMIT - 1].rstrip() + "…"

    # 3) 其它：按中文句读截
    if len(d) <= LIMIT:
        return d
    cut = re.split(r"[。，,；;（(]", d)[0].strip()
    if len(cut) + 1 <= LIMIT and cut:
        return cut + ("…" if cut != d else "")
    return d[: LIMIT - 1].rstrip() + "…"


def yaml_safe(value: str) -> str:
    if re.search(r'[:#\-\[\]{}&*!|>\'"%@`]', value) or value != value.strip():
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return '"' + value.replace('"', '\\"') + '"'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    changed = []
    for p in sorted(ROOT.rglob("SKILL.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.match(r"^(---\s*\n.*?^\s*description:\s*)(.*?)(\s*\n.*?^---)", text, re.S | re.M)
        if not m:
            continue
        raw = m.group(2).strip()
        value = raw.strip('"').strip("'")
        if len(value) <= 60:
            continue
        new = compress(value)
        if new == value:
            continue
        changed.append((str(p.relative_to(ROOT.parent)), len(value), len(new), value[:70], new))
        if not args.dry_run:
            new_text = text[: m.start(2)] + yaml_safe(new) + text[m.end(2):]
            p.write_text(new_text, encoding="utf-8")

    for path, old_len, new_len, old, new in changed[:15]:
        print(f"{old_len:>3}->{new_len:<3} {path}\n      {old}\n   => {new}")
    print(f"\n共 {'将' if args.dry_run else '已'} 修改 {len(changed)} 个技能")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
