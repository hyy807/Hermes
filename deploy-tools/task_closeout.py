#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务收尾：审计本次任务的全部产物，关键归档、中间压缩、废弃清理。

么西么西确认任务完成后跑这个。默认 dry-run，看清清单再 --apply。

分类规则（可改下面的表）
  KEEP     报告 / 订阅 / 账号本 / PoC 与提取脚本 —— 原样归档，永不自动删
  ARCHIVE  中间产物（原始 jsonl、列表 txt、扫描输出）—— 归档并压缩
  DROP     空文件 / 日志 / 临时 / 缓存 / 备份 —— 清理

产物去向
  /root/apks/archive/<目标>/<YYYY-MM-DD>/
      ├── keep/           关键产物（保留原名）
      ├── raw.tar.gz      中间产物打包
      └── closeout.json   本次收尾清单（含 sha256）

用法
  python3 task_closeout.py --contract <契约.json> --workdir /root/apks/recon/<目标>
  python3 task_closeout.py --workdir <目录> --apply          # 真删（确认清单后）
  python3 task_closeout.py --workdir <目录> --target x.com --apply

安全
  - 默认 dry-run，只打印不移动不删除
  - DROP 必须命中规则；没命中规则的未知文件一律保留并提示
  - 归档用复制 + 哈希核对，核对通过才动原文件
"""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import sys
import shutil
import tarfile
import time
from pathlib import Path

ARCHIVE_ROOT = Path("/root/apks/archive")

KEEP_PATTERNS = [
    "*.md", "*.pdf", "*.html", "*.htm",            # 报告
    "*.yml", "*.yaml",                              # 订阅 / 配置
    "*access*.mp4",                                 # 截图录像（如有）
]
KEEP_NAME_HINTS = [
    "report", "报告", "account", "accounts", "hits", "hits_", "subs",
    "poc", "exploit", "extract", "spider", "payload", "index",
]
ARCHIVE_PATTERNS = ["*.jsonl", "*.ndjson", "*.csv", "*.txt", "*.xml", "*.json", "*.db"]
# *.log 故意不在这里：命中日志常常就是证据，误删不可逆，统一进 UNKNOWN 人工判断
DROP_PATTERNS = [
    "*.tmp", "*.temp", "*.bak", "*.swp", "*.pyc", "*.pyo", "*.err",
    "*.retry", "*.lock", ".DS_Store", "Thumbs.db",
]
LOG_PATTERNS = ["*.log", "*.out"]
DROP_DIRS = ["__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"]


def safe_target(raw: str) -> str:
    """归档目录名只允许 [A-Za-z0-9._-]，挡掉 .. / 反斜杠 / 控制字符 / 跨平台特殊名。"""
    s = str(raw or "").strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._-")
    if not s or s in (".", ".."):
        raise SystemExit(f"归档目标名不合法: {raw!r}")
    return s[:80]


def sha256(p: Path, limit: int = 64 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
            if limit and h.digest_size and fh.tell() > limit:
                break
    return h.hexdigest()


def classify(p: Path) -> str:
    name = p.name
    low = name.lower()
    if p.is_dir():
        return "DROP" if name in DROP_DIRS else "KEEP"
    try:
        if p.stat().st_size == 0:
            return "DROP"
    except OSError:
        return "KEEP"
    if any(fnmatch.fnmatch(low, pat) for pat in DROP_PATTERNS):
        return "DROP"
    if any(fnmatch.fnmatch(low, pat) for pat in LOG_PATTERNS):
        return "UNKNOWN"          # 日志可能是证据，不自动删
    if any(h in low for h in KEEP_NAME_HINTS):
        return "KEEP"
    if any(fnmatch.fnmatch(low, pat) for pat in KEEP_PATTERNS):
        return "KEEP"
    if any(fnmatch.fnmatch(low, pat) for pat in ARCHIVE_PATTERNS):
        return "ARCHIVE"
    return "UNKNOWN"          # 不认识就保留，别自作聪明删


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", action="append", required=True, help="任务产物目录，可多次给")
    ap.add_argument("--contract", default="", help="任务契约（会把归档后的路径写回去）")
    ap.add_argument("--target", default="", help="归档子目录名，默认取契约 target 或工作目录名")
    ap.add_argument("--apply", action="store_true", help="真的归档/删除（默认只打印）")
    args = ap.parse_args()

    contract = None
    if args.contract:
        try:
            contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"契约读不了: {exc}")
            return 2
        target = args.target or contract.get("target") or "unknown"
    else:
        target = args.target or Path(args.workdir[0]).name

    stamp = time.strftime("%Y-%m-%d")
    if args.contract:
        cid = hashlib.sha256(str(Path(args.contract).resolve()).encode()).hexdigest()[:8]
    else:
        cid = "run" + time.strftime("%H%M%S")
    dest = (ARCHIVE_ROOT / safe_target(target) / f"{stamp}_{cid}").resolve()
    root_resolved = ARCHIVE_ROOT.resolve()
    if root_resolved not in dest.parents:
        raise SystemExit(f"归档路径越界: {dest}")

    # 契约里任何被引用的证据都必须留在可访问的原路径上：
    # 打包进 tar 后 evidence.path 就指向不存在的文件，verify 会全部失败。
    protected: set[str] = set()
    if contract:
        for ev in contract.get("evidence", []):
            try:
                protected.add(str(Path(ev.get("path", "")).resolve()))
            except (OSError, ValueError):
                continue

    buckets: dict[str, list[Path]] = {"KEEP": [], "ARCHIVE": [], "DROP": [], "UNKNOWN": []}
    for wd in args.workdir:
        root = Path(wd)
        if not root.exists():
            print(f"跳过不存在的目录: {root}")
            continue
        for p in sorted(root.rglob("*")):
            if p.is_dir() and p.name not in DROP_DIRS:
                continue
            # 缓存目录整体按目录处理，内部的单个文件不再单独记一次
            if any(part in DROP_DIRS for part in p.parts):
                if p.is_dir() and p.name in DROP_DIRS:
                    buckets["DROP"].append(p)
                continue
            try:
                if str(p.resolve()) in protected:
                    buckets["KEEP"].append(p)      # 被契约引用的证据不降级
                    continue
            except (OSError, ValueError):
                pass
            buckets[classify(p)].append(p)

    size = {k: sum(f.stat().st_size for f in v if f.is_file()) for k, v in buckets.items()}

    print(f"=== 收尾审计 target={target} ===")
    for k in ("KEEP", "ARCHIVE", "DROP", "UNKNOWN"):
        print(f"  {k:<8} {len(buckets[k]):>4} 个  {human(size[k]):>9}")
    lock_key = hashlib.sha256(
        str(Path(args.contract or args.workdir[0]).resolve()).encode()).hexdigest()[:12]
    lock_path = Path(os.environ.get("TMPDIR", "/tmp")) / f"closeout_{lock_key}.lock"
    lock_fh = lock_path.open("w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"同一任务已有 closeout 在跑（{lock_path}），拒绝并发")

    print(f"\n归档目录: {dest}")
    print(f"模式: {'APPLY（会移动+删除）' if args.apply else 'DRY-RUN（只打印）'}")

    for k in ("KEEP", "ARCHIVE", "DROP", "UNKNOWN"):
        if not buckets[k]:
            continue
        print(f"\n--- {k} ---")
        for f in buckets[k][:25]:
            try:
                print(f"  {human(f.stat().st_size):>9}  {f}")
            except OSError:
                print(f"  {'?':>9}  {f}")
        if len(buckets[k]) > 25:
            print(f"  … 另外 {len(buckets[k]) - 25} 个")

    if buckets["UNKNOWN"]:
        print("\n!! 有未识别文件：默认保留，请人工过一眼再决定（改 classify 规则或手动处理）")

    manifest = {
        "target": target, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workdirs": args.workdir, "apply": args.apply,
        "counts": {k: len(v) for k, v in buckets.items()},
        "bytes": size,
        "keep": [], "raw": [], "dropped": [], "unknown": [],
    }

    if not args.apply:
        print("\n（dry-run：什么都没动。确认清单后加 --apply 执行）")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    keep_dir = dest / "keep"
    keep_dir.mkdir(exist_ok=True)
    pending_keep: list[Path] = []
    pending_archive: list[Path] = []

    def src_root_of(f: Path) -> Path | None:
        for w in args.workdir:
            wp = Path(w)
            if wp in f.parents or wp == f.parent:
                return wp
        return None

    # 1) KEEP：复制 + 哈希核对（此时不动原文件）
    for f in buckets["KEEP"]:
        if not f.is_file():
            continue
        src_hash = sha256(f)
        root = src_root_of(f)
        arc = str(root.name / f.relative_to(root)) if root else f.name
        out = keep_dir / arc
        out.parent.mkdir(parents=True, exist_ok=True)
        n = 1
        while out.exists() and sha256(out) != src_hash:
            out = out.with_name(f"{out.stem}_{n}{out.suffix}")
            n += 1
        shutil.copy2(f, out)
        if sha256(out) == src_hash:
            manifest["keep"].append({"name": str(out.relative_to(dest)), "sha256": src_hash,
                                     "bytes": f.stat().st_size, "from": str(f)})
            pending_keep.append(f)
        else:
            print(f"  !! 哈希不符，原文件保留: {f}")

    # 2) ARCHIVE：打包后逐个成员校验，校验不过就一个都不删
    if buckets["ARCHIVE"]:
        pairs = []
        used = set()
        for f in buckets["ARCHIVE"]:
            if not f.is_file():
                continue
            root = src_root_of(f)
            arc = str(root.name / f.relative_to(root)) if root else f"misc/{f.name}"
            while arc in used:                       # 不同 workdir 同名时加后缀
                stem, dot, ext = arc.rpartition(".")
                arc = f"{stem}_{len(used)}{dot}{ext}"
            used.add(arc)
            pairs.append((f, arc))
        tar_path = dest / "raw.tar.gz"
        src_meta = {arc: (sha256(f), f.stat().st_size) for f, arc in pairs}
        with tarfile.open(tar_path, "w:gz") as tf:
            for f, arc in pairs:
                tf.add(f, arcname=arc)
        bad = []
        with tarfile.open(tar_path) as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                want_hash, want_size = src_meta.get(m.name, ("", -1))
                if m.size != want_size:
                    bad.append((m.name, "size"))
                    continue
                fh = tf.extractfile(m)
                h = hashlib.sha256()
                while chunk := fh.read(1 << 20):
                    h.update(chunk)
                if h.hexdigest() != want_hash:
                    bad.append((m.name, "sha256"))
            missing = [arc for _, arc in pairs if arc not in {m.name for m in tf.getmembers()}]
        if missing:
            bad += [(m, "missing-member") for m in missing]
        if bad:
            print(f"  !! 归档校验失败（逐成员哈希），源文件全部保留: {bad[:3]}")
            manifest["archive_failed"] = [str(m) for m, _ in bad]
        else:
            manifest["raw"].append({"name": tar_path.name, "sha256": sha256(tar_path),
                                    "bytes": tar_path.stat().st_size, "files": len(pairs)})
            pending_archive = [f for f, _ in pairs]

    # 3) 先把契约指过去（读回校验），再删原文件 —— 中途断掉也不会留下断链
    if contract and args.contract:
        moved = {Path(e["from"]).resolve(): dest / e["name"] for e in manifest["keep"]}
        changed = 0
        for ev in contract.get("evidence", []):
            newp = moved.get(Path(ev.get("path", "")).resolve())
            if newp and newp.is_file():
                ev["path"] = str(newp)
                ev["sha256"] = sha256(newp)
                changed += 1
        if changed:
            tmp = Path(args.contract).with_suffix(".tmp.json")
            tmp.write_text(json.dumps(contract, ensure_ascii=False, indent=1), encoding="utf-8")
            back = json.loads(tmp.read_text(encoding="utf-8"))
            ok = all(Path(e.get("path", "")).is_file() for e in back.get("evidence", []))
            if not ok:
                print("  !! 契约回读校验失败，原文件不删，契约不改")
                tmp.unlink(missing_ok=True)
                return 3
            tmp.replace(args.contract)
        print(f"\n契约更新: {changed} 条证据路径改到归档目录")

    # 4) 全部核对通过，才删源文件
    for f in pending_keep + pending_archive:
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"  !! 删不掉 {f}: {exc}")

    # 5) DROP：删完要确认真的没了
    failed_del = []
    for f in buckets["DROP"]:
        try:
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"  !! 删不掉 {f}: {exc}")
        if f.exists():
            failed_del.append(str(f))
        else:
            manifest["dropped"].append(str(f))

    manifest["delete_failed"] = failed_del
    manifest["state"] = "partial" if failed_del else "complete"
    manifest["unknown"] = [str(f) for f in buckets["UNKNOWN"]]
    with (dest / "closeout.json").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, ensure_ascii=False, indent=1))
        fh.flush()
        os.fsync(fh.fileno())

    print(f"\n完成。归档 {len(manifest['keep'])} 个关键产物"
          f"{' + raw.tar.gz' if manifest['raw'] else ''}，清理 {len(manifest['dropped'])} 个废弃项")
    if failed_del:
        print(f"!! {len(failed_del)} 项没删掉，见 closeout.json 的 delete_failed")
    print(f"清单: {dest/'closeout.json'}")
    return 1 if failed_del else 0


if __name__ == "__main__":
    raise SystemExit(main())
