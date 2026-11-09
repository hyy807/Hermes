#!/usr/bin/env python3
"""扫描技能正文里引用的 scripts/ references/ templates/ assets/ 路径，
逐一核对文件是否存在；同时列出「存在但正文没提」的孤儿文件。

只把「像文件」的引用当引用（最后一段带扩展名，如 x.py / y.md / z.sh）；
`templates/lagom2`、`assets/api_`、`references/...` 这类是正文里的产品/主题名
或占位符，不算引用 —— 之前把它们算进去会产出假阳性。

用法:
  python3 check_skill_refs.py                        # 默认扫 ~/.hermes/skills（运行态）
  python3 check_skill_refs.py --root /root/Hermes/skills --root /root/Hermes/skills-local
  python3 check_skill_refs.py --json out.json
退出码：缺失数 > 0 时为 1。
"""
import argparse
import json
import os
import re
import sys

PAT = re.compile(r'(?<![\w./-])(?:\./)?((?:scripts|references|templates|assets)/[A-Za-z0-9._\-/]+[A-Za-z0-9._-])')
FILE_RE = re.compile(r'^[A-Za-z0-9._-]+\.[A-Za-z0-9]{1,8}$')
INTERNAL = re.compile(r'^_[A-Za-z0-9_]+\.py$')   # 被兄弟脚本 import 的内部模块，SKILL.md 不必点名
SUPPORT = {"go.mod", "go.sum", "package.json", "package-lock.json", "requirements.txt",
           "tsconfig.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.toml", "Cargo.lock"}



def skill_dirs(roots):
    for root in roots:
        for dirpath, _dirnames, filenames in os.walk(root):
            if "SKILL.md" in filenames:
                yield dirpath


def is_file_ref(ref: str) -> bool:
    last = ref.rsplit("/", 1)[-1]
    return bool(FILE_RE.match(last)) and not last.startswith("...")


def scan(roots):
    missing, orphans, prose = [], [], []
    nskills = 0
    for d in skill_dirs(roots):
        nskills += 1
        name = os.path.basename(d)
        text = open(os.path.join(d, "SKILL.md"), encoding="utf-8", errors="replace").read()
        for ref in sorted(set(PAT.findall(text))):
            if not is_file_ref(ref):
                prose.append({"skill": name, "ref": ref})
                continue
            if os.path.isfile(os.path.join(d, ref)):
                continue
            lines = [i + 1 for i, l in enumerate(text.splitlines()) if ref in l][:3]
            missing.append({"skill": name, "dir": d, "ref": ref, "lines": lines})
        for sub in ("scripts", "references", "templates", "assets"):
            sd = os.path.join(d, sub)
            if not os.path.isdir(sd):
                continue
            for f in sorted(os.listdir(sd)):
                fp = os.path.join(sd, f)
                if not os.path.isfile(fp):
                    continue
                rel = f"{sub}/{f}"
                if rel in text or f in text:
                    continue
                if INTERNAL.match(f):
                    continue      # 支持模块，被同级脚本 import，不需要 SKILL.md 提到
                if f in SUPPORT:
                    continue      # 构建清单，属于同级脚本的依赖，不是独立交付物
                siblings = os.listdir(sd)
                imported = False
                if f.endswith(".py"):
                    stem = f[:-3]
                    for s in siblings:
                        if s.endswith(".py") and s != f:
                            body = open(os.path.join(sd, s), encoding="utf-8", errors="replace").read()
                            if re.search(rf'(^|\n)\s*(from|import)\s+{re.escape(stem)}\b', body):
                                imported = True
                                break
                if imported:
                    continue
                orphans.append({"skill": name, "file": rel,
                                "kb": round(os.path.getsize(fp) / 1024, 1)})
    return nskills, missing, orphans, prose


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", action="append", default=[])
    ap.add_argument("--json", default="")
    ap.add_argument("--all", action="store_true", help="也打印被忽略的正文路径")
    a = ap.parse_args()
    roots = a.root or [os.path.expanduser("~/.hermes/skills")]
    roots = [r for r in roots if os.path.isdir(r)]
    if not roots:
        sys.stderr.write("no skill roots found\n")
        return 2

    n, missing, orphans, prose = scan(roots)
    print(f"roots: {', '.join(roots)}")
    print(f"技能数: {n}  缺失引用: {len(missing)}  孤儿文件: {len(orphans)}")
    print("\n== 缺失 ==")
    for m in missing:
        print(f"{m['skill']:42s} {m['ref']:48s} L{m['lines']}")
    print("\n== 孤儿（存在但 SKILL.md 没提）==")
    for o in orphans:
        print(f"{o['skill']:42s} {o['file']:48s} {o['kb']}KB")
    if a.all:
        print("\n== 忽略的正文路径（非文件引用）==")
        for p in prose:
            print(f"{p['skill']:42s} {p['ref']}")
    if a.json:
        json.dump({"missing": missing, "orphans": orphans, "prose": prose},
                  open(a.json, "w"), ensure_ascii=False, indent=1)
        print(f"\n写入 {a.json}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
