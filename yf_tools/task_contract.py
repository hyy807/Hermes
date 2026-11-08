"""Task contract: the structured form of "what this run is allowed to do, and what counts as done".

Why this exists
---------------
A prompt that says "targets come from 么西么西" is advice; it does not stop a scanner. This module
turns that advice into a file the executors read, and a completion check that fails when the
evidence does not back the claim.

Design
------
* One JSON document per task, plain stdlib, atomic writes, no daemons.
* State machine: draft -> ready -> running -> verify -> delivered, plus blocked/failed/stopped.
* Evidence entries carry path + sha256 + timestamp, so a later reader can prove the bytes are
  the ones that were produced (a pointer alone rots).
* Findings are tri-state: observed (saw it) / candidate (needs review) / confirmed (reproduced).
* close() refuses to deliver when evidence is missing, a hash no longer matches, or a promised
  deliverable was never produced — "the workflow ran" is not "the task is done".

CLI
---
    python3 -m yf_tools.task_contract new    --target T --operation active -o c.json
    python3 -m yf_tools.task_contract set    c.json --scope a.example --egress 127.0.0.1:7890
    python3 -m yf_tools.task_contract state  c.json ready
    python3 -m yf_tools.task_contract evidence c.json --path /root/apks/x.yml --kind sub
    python3 -m yf_tools.task_contract finding  c.json --id F1 --status candidate --note "..."
    python3 -m yf_tools.task_contract coverage c.json --planned 100 --done 74
    python3 -m yf_tools.task_contract verify c.json
    python3 -m yf_tools.task_contract close  c.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OPERATIONS = ("read_only", "low_impact", "active", "validation")
STATES = ("draft", "ready", "running", "verify", "delivered", "blocked", "failed", "stopped")
FINDING_STATES = ("observed", "candidate", "confirmed")

# Allowed transitions. blocked/failed/stopped are reachable from any live state.
_TRANSITIONS = {
    "draft": {"ready", "blocked", "failed", "stopped"},
    "ready": {"running", "blocked", "failed", "stopped"},
    "running": {"verify", "blocked", "failed", "stopped"},
    "verify": {"delivered", "running", "blocked", "failed", "stopped"},
    "delivered": set(),
    "blocked": {"ready", "stopped"},
    "failed": {"ready", "stopped"},
    "stopped": set(),
}


class ContractError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ContractError(f"contract not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"contract is not valid JSON: {exc}") from exc
    if data.get("kind") != "yf_task_contract":
        raise ContractError("not a yf_task_contract document")
    return data


def save(path: str | Path, data: dict) -> None:
    data["updated_at"] = _now()
    _atomic_write(Path(path), data)


def new(target: str, operation: str = "active", task: str = "") -> dict:
    if not isinstance(target, str) or not target.strip():
        raise ContractError("target is required")
    if operation not in OPERATIONS:
        raise ContractError(f"operation must be one of {OPERATIONS}")
    return {
        "kind": "yf_task_contract",
        "version": 1,
        "task": task or target,
        "target": target.strip(),
        "operation": operation,
        "state": "draft",
        "scope": [],
        "forbidden": [],
        "egress": "",
        "deliverables": [],
        "evidence": [],
        "findings": [],
        "coverage": {"planned": 0, "done": 0, "skipped": []},
        "unmet": [],
        "history": [{"at": _now(), "event": "created", "target": target, "operation": operation}],
        "created_at": _now(),
        "updated_at": _now(),
    }


def set_state(data: dict, new_state: str, force: bool = False) -> dict:
    if new_state not in STATES:
        raise ContractError(f"state must be one of {STATES}")
    if data.get("state") == "delivered" and new_state != "delivered" and not force:
        raise ContractError("delivered 不能直接回退；要改先 reopen")
    cur = data.get("state", "draft")
    if new_state == cur:
        return data
    if new_state not in _TRANSITIONS.get(cur, set()):
        raise ContractError(f"illegal transition {cur} -> {new_state}")
    if new_state == "ready":
        if not data.get("target"):
            raise ContractError("cannot ready a contract without a target")
        if not data.get("scope"):
            raise ContractError("cannot ready a contract without an explicit scope list")
    if new_state == "verify" and cur == "running":
        done = int((data.get("coverage") or {}).get("done") or 0)
        if done <= 0:
            raise ContractError("done=0：没有任何已完成的计划项，不能进 verify")
    data["state"] = new_state
    data.setdefault("history", []).append({"at": _now(), "event": "state", "from": cur, "to": new_state})
    return data


_SNAPSHOT_FIELDS = ("target", "scope", "forbidden", "egress", "egress_socks5",
                    "deliverables", "evidence", "findings", "coverage")


def _snapshot_fields(data: dict) -> dict:
    return {k: data.get(k) for k in _SNAPSHOT_FIELDS}


def _snapshot_hash(data: dict) -> str:
    blob = json.dumps(_snapshot_fields(data), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def reopen(data: dict, reason: str = "") -> dict:
    """把已交付的契约拉回 running 做补充。

    交付时的证据/发现/覆盖度会原样封存进 delivered_snapshots，带哈希；
    reopen 后可以改当前内容，但改不动已封存的那一份。
    """
    if data.get("state") != "delivered":
        raise ContractError(f"只有 delivered 才能 reopen（当前 {data.get('state')}）")
    snap = {
        "at": data.get("delivered_at") or _now(),
        "sha256": data.get("snapshot_sha256") or _snapshot_hash(data),
        "reason": reason,
        "content": _snapshot_fields(data),
    }
    data.setdefault("delivered_snapshots", []).append(snap)
    data["state"] = "running"
    data.pop("snapshot_sha256", None)
    data.setdefault("history", []).append(
        {"at": _now(), "event": "reopen", "from": "delivered",
         "reason": reason, "sealed_sha256": snap["sha256"]})
    return data


def _assert_mutable(data: dict) -> None:
    """已交付的契约只读：否则交付记录可以被事后改写，审计属性就没了。"""
    if data.get("state") == "delivered":
        raise ContractError("契约已 delivered，只读；要改先 task_contract reopen")


def add_evidence(data: dict, path: str, kind: str = "artifact", note: str = "") -> dict:
    _assert_mutable(data)
    p = Path(path)
    if not p.is_file():
        raise ContractError(f"evidence file does not exist: {p}")
    entry = {
        "id": f"E{len(data.get('evidence') or []) + 1}",
        "path": str(p.resolve()),
        "sha256": _sha256(p),
        "bytes": p.stat().st_size,
        "kind": kind,
        "note": note,
        "at": _now(),
    }
    ev = data.setdefault("evidence", [])
    for existing in ev:
        if existing.get("path") == entry["path"] and existing.get("sha256") == entry["sha256"]:
            return data  # same bytes already registered
    ev.append(entry)
    return data


def add_finding(data: dict, fid: str, status: str, note: str = "", target: str = "",
                evidence_ids: list | None = None) -> dict:
    """登记发现。confirmed 必须绑定具体的 evidence id，不能只是「有任意证据」。

    只检查「存在某类证据」时，拿一个无关的 hosts.txt 就能把 finding 标成已复现。
    """
    _assert_mutable(data)
    if status not in FINDING_STATES:
        raise ContractError(f"finding status must be one of {FINDING_STATES}")
    ids = [str(x) for x in (evidence_ids or [])]
    if status == "confirmed":
        if not ids:
            raise ContractError(
                "confirmed finding 必须用 --evidence 绑定证据 ID（先 task_contract evidence 登记，再看返回的 id）")
        known = {e.get("id") for e in data.get("evidence") or []}
        missing = [i for i in ids if i not in known]
        if missing:
            raise ContractError(f"evidence id 不存在: {missing}（已登记: {sorted(known)}）")
    findings = data.setdefault("findings", [])
    for item in findings:
        if item.get("id") == fid:
            item.update({"status": status, "note": note, "at": _now()})
            if ids:
                item["evidence_ids"] = ids
            if target:
                item["target"] = target
            return data
    findings.append({"id": fid, "status": status, "note": note,
                     "target": target or data.get("target", ""),
                     "evidence_ids": ids, "at": _now()})
    return data


def add_done(data: dict, task_id: str, evidence_ids: list, note: str = "") -> dict:
    """登记一个「已完成」的计划项，必须带结果证据。

    只填一个 done 数字等于自称做过；每项都挂证据，才能回头查。
    done 数字由这里自动维护，不再手填。
    """
    _assert_mutable(data)
    task_id = (task_id or "").strip()
    if not task_id:
        raise ContractError("done 项需要 --id（如 http:host:443）")
    ids = [str(x) for x in (evidence_ids or []) if str(x).strip()]
    if not ids:
        raise ContractError("完成项必须用 --evidence 绑定结果证据")
    known = {e.get("id") for e in data.get("evidence") or []}
    missing = [i for i in ids if i not in known]
    if missing:
        raise ContractError(f"evidence id 不存在: {missing}（已登记: {sorted(known)}）")
    cov = data.setdefault("coverage", {"planned": 0, "done": 0, "skipped": []})
    items = cov.setdefault("done_items", [])
    if any(i.get("id") == task_id for i in items):
        raise ContractError(f"done id 重复: {task_id}")
    planned = int(cov.get("planned") or 0)
    if planned and len(items) >= planned:
        raise ContractError(f"完成项已达 planned={planned}，先把 planned 加上去")
    items.append({"id": task_id, "evidence_ids": ids, "note": note, "at": _now()})
    cov["done"] = len(items)
    return data


def _skipped_items(cov: dict) -> list[dict]:
    """把 skipped 统一成 [{id, reason, at}]。旧格式（纯字符串）视为无原因。"""
    out = []
    for item in cov.get("skipped") or []:
        if isinstance(item, dict):
            out.append(item)
        else:
            out.append({"id": str(item), "reason": "", "legacy": True})
    return out


def add_skipped(data: dict, task_id: str, reason: str) -> dict:
    """登记一个「计划内但跳过」的任务。必须有 id 和原因，且不能超过未完成数。

    只允许字符串列表时，把 ["x","x","x",...] 塞满就能让 coverage 看起来齐了 ——
    所以 id 唯一、原因必填、数量封顶三条都在这里挡住。
    """
    _assert_mutable(data)
    task_id = (task_id or "").strip()
    reason = (reason or "").strip()
    if not task_id or not reason:
        raise ContractError("skip 需要 --id 和 --reason（缺原因等于没说）")
    cov = data.setdefault("coverage", {"planned": 0, "done": 0, "skipped": []})
    items = _skipped_items(cov)
    cov["skipped"] = items
    if any(i.get("id") == task_id for i in items):
        raise ContractError(f"skip id 重复: {task_id}")
    planned, done = int(cov.get("planned") or 0), int(cov.get("done") or 0)
    if planned and len(items) >= max(0, planned - done):
        raise ContractError(
            f"skip 数量超过未完成数（planned {planned}, done {done}, 已 skip {len(items)}）")
    items.append({"id": task_id, "reason": reason, "at": _now()})
    return data


def set_coverage(data: dict, planned: int | None = None, done: int | None = None,
                 skipped: list | None = None) -> dict:
    _assert_mutable(data)
    cov = data.setdefault("coverage", {"planned": 0, "done": 0, "skipped": []})
    if planned is not None:
        if int(planned) < 0:
            raise ContractError(f"planned 不能为负: {planned}")
        cov["planned"] = int(planned)
    if done is not None:
        if int(done) < 0:
            raise ContractError(f"done 不能为负: {done}")
        cov["done"] = int(done)
    if skipped:
        cov["skipped"] = [s if isinstance(s, dict) else {"id": str(s), "reason": "", "legacy": True}
                          for s in skipped]
    return data


def verify(data: dict) -> list[str]:
    """Return the list of unmet conditions. Empty list = the contract can be delivered."""
    problems: list[str] = []

    if data.get("state") not in ("verify", "delivered"):
        problems.append(f"state is {data.get('state')}, expected verify before delivery")

    if not data.get("scope"):
        problems.append("no scope recorded")

    for idx, ev in enumerate(data.get("evidence", [])):
        path = Path(ev.get("path", ""))
        if not path.is_file():
            problems.append(f"evidence[{idx}] missing on disk: {ev.get('path')}")
            continue
        current = _sha256(path)
        if current != ev.get("sha256"):
            problems.append(
                f"evidence[{idx}] hash changed ({ev.get('path')}): "
                f"recorded {str(ev.get('sha256'))[:12]} now {current[:12]}"
            )

    ev_by_id = {e.get("id"): e for e in data.get("evidence") or []}
    for item in data.get("findings", []):
        if item.get("status") != "confirmed":
            continue
        ids = [str(x) for x in (item.get("evidence_ids") or [])]
        if not ids:
            problems.append(
                f"finding {item.get('id')} 标了 confirmed 但没绑定 evidence_ids（无法证明是这个洞的证据）")
            continue
        for eid in ids:
            ev = ev_by_id.get(eid)
            if not ev:
                problems.append(f"finding {item.get('id')} 引用的 {eid} 不存在")
            elif ev.get("kind") not in ("poc", "repro", "artifact", "raw"):
                problems.append(
                    f"finding {item.get('id')} 的 {eid} 类型是 {ev.get('kind')}，不算复现证据")

    cov = data.get("coverage") or {}
    try:
        planned, done = int(cov.get("planned") or 0), int(cov.get("done") or 0)
    except (TypeError, ValueError):
        problems.append("coverage.planned/done 不是整数")
        planned, done = 0, 0
    if planned < 0:
        problems.append(f"coverage.planned 为负: {planned}")
    if done < 0:
        problems.append(f"coverage.done 为负: {done}")
    if planned > 0 and done > planned:
        problems.append(f"coverage.done ({done}) 大于 planned ({planned})")
    if planned == 0:
        problems.append(
            "coverage.planned 未登记：没有计划项就不能证明做过测试，"
            "至少登记 1 项（task_contract coverage <契约> --planned N）")
    done_items = cov.get("done_items") or []
    if done > 0 and len(done_items) != done:
        problems.append(
            f"coverage.done={done} 但只登记了 {len(done_items)} 个完成项；"
            f"done 必须由 task_contract done 逐项登记（不能用数字冒充）")
    for i, it in enumerate(done_items):
        if not (it.get("evidence_ids") or []):
            problems.append(f"done_items[{i}] ({it.get('id')}) 没绑定结果证据")
    skipped = _skipped_items(cov)
    if skipped:
        ids = [s.get("id") for s in skipped]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            problems.append(f"skipped 有重复 id（覆盖度不可信）: {sorted(dup)[:3]}")
        no_reason = [s.get("id") for s in skipped if not (s.get("reason") or "").strip()]
        if no_reason:
            problems.append(f"skipped 缺原因: {no_reason[:3]}")
        if len(skipped) > max(0, planned - done):
            problems.append(
                f"skipped 数量超过未完成数（planned {planned}, done {done}, skipped {len(skipped)}）")
    if planned and done < planned:
        unexplained = planned - done - len(skipped)
        if unexplained > 0:
            problems.append(
                f"coverage incomplete: planned {planned}, done {done}, "
                f"skipped {len(skipped)}, unexplained {unexplained}"
            )

    registered = {str(Path(ev.get("path", "")).resolve()): ev for ev in data.get("evidence") or []}
    for name in data.get("deliverables", []):
        want = Path(str(name)).expanduser()
        if not want.is_absolute():
            problems.append(f"deliverable 必须是绝对路径（按文件名匹配会串证据）: {name}")
            continue
        key = str(want.resolve())
        if key not in registered:
            problems.append(f"deliverable 没登记成证据: {name}")
        else:
            ev = registered[key]
            if not Path(key).is_file():
                problems.append(f"deliverable 文件不存在: {name}")
            elif _sha256(Path(key)) != ev.get("sha256"):
                problems.append(f"deliverable 内容变了（与登记时哈希不符）: {name}")

    return problems


def close(data: dict) -> dict:
    problems = verify(data)
    data["unmet"] = problems
    if problems:
        if data.get("state") in ("ready", "running", "blocked", "failed"):
            data["state"] = "verify"
        data.setdefault("history", []).append(
            {"at": _now(), "event": "close_refused", "unmet": len(problems)})
        return data
    data["state"] = "delivered"
    data["delivered_at"] = _now()
    data["snapshot_sha256"] = _snapshot_hash(data)
    data.setdefault("history", []).append({"at": _now(), "event": "delivered"})
    return data


# ---------------------------------------------------------------- CLI


def _parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="task_contract", description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="create a draft contract")
    p_new.add_argument("--target", required=True)
    p_new.add_argument("--operation", default="active", choices=OPERATIONS)
    p_new.add_argument("--task", default="")
    p_new.add_argument("-o", "--out", required=True)

    p_set = sub.add_parser("set", help="update scope / forbidden / egress / deliverables")
    p_set.add_argument("file")
    p_set.add_argument("--scope", action="append", default=None)
    p_set.add_argument("--forbidden", action="append", default=None)
    p_set.add_argument("--egress", default=None)
    p_set.add_argument("--egress-socks5", default=None, help="naabu 用的 socks5 出口，必须显式声明")
    p_set.add_argument("--deliverable", action="append", default=None)

    p_state = sub.add_parser("state", help="move the state machine")
    p_state.add_argument("file")
    p_state.add_argument("state", choices=STATES)

    p_ev = sub.add_parser("evidence", help="register an artifact with its hash")
    p_ev.add_argument("file")
    p_ev.add_argument("--path", required=True)
    p_ev.add_argument("--kind", default="artifact")
    p_ev.add_argument("--note", default="")

    p_f = sub.add_parser("finding", help="record a finding (observed/candidate/confirmed)")
    p_f.add_argument("file")
    p_f.add_argument("--id", required=True)
    p_f.add_argument("--status", required=True, choices=FINDING_STATES)
    p_f.add_argument("--note", default="")
    p_f.add_argument("--target", default="")
    p_f.add_argument("--evidence", default="", help="证据 ID，逗号分隔（confirmed 必填），如 E1,E2")

    p_c = sub.add_parser("coverage", help="record planned/done/skipped")
    p_c.add_argument("file")
    p_c.add_argument("--planned", type=int, default=None)
    p_c.add_argument("--done", type=int, default=None)
    p_c.add_argument("--skipped", action="append", default=None)

    p_done = sub.add_parser("done", help="登记一个已完成项（必须带证据）")
    p_done.add_argument("file")
    p_done.add_argument("--id", required=True, help="如 http:example.com:443")
    p_done.add_argument("--evidence", required=True, help="证据 ID，逗号分隔")
    p_done.add_argument("--note", default="")

    p_re = sub.add_parser("reopen", help="把 delivered 拉回 running 继续补")
    p_re.add_argument("file")
    p_re.add_argument("--reason", default="")

    p_skip = sub.add_parser("skip", help="记录一个计划内跳过的任务（必须有原因）")
    p_skip.add_argument("file")
    p_skip.add_argument("--id", required=True, help="任务标识，如 http-baseline:host:443")
    p_skip.add_argument("--reason", required=True)

    p_v = sub.add_parser("verify", help="check without closing")
    p_v.add_argument("file")

    p_close = sub.add_parser("close", help="close; refuses delivery while conditions are unmet")
    p_close.add_argument("file")

    p_show = sub.add_parser("show", help="print a summary")
    p_show.add_argument("file")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.cmd == "new":
        data = new(args.target, args.operation, args.task)
        save(args.out, data)
        print(json.dumps({"created": args.out, "state": data["state"]}, ensure_ascii=False))
        return 0

    data = load(args.file)

    if args.cmd == "set":
        _assert_mutable(data)
        if args.scope:
            data["scope"] = list(args.scope)
        if args.forbidden:
            data["forbidden"] = list(args.forbidden)
        if args.egress is not None:
            data["egress"] = args.egress
        if args.egress_socks5 is not None:
            data["egress_socks5"] = args.egress_socks5
        if args.deliverable:
            data["deliverables"] = list(args.deliverable)
        save(args.file, data)
        print("updated")
        return 0

    if args.cmd == "state":
        set_state(data, args.state)
        save(args.file, data)
        print(f"state={data['state']}")
        return 0

    if args.cmd == "evidence":
        add_evidence(data, args.path, args.kind, args.note)
        save(args.file, data)
        last = (data.get("evidence") or [])[-1]
        print(f"{last.get('id')}  {Path(last.get('path','')).name}  "
              f"{last.get('bytes')}B  sha256={str(last.get('sha256'))[:12]}")
        return 0

    if args.cmd == "finding":
        ids = [x.strip() for x in (args.evidence or "").split(",") if x.strip()]
        add_finding(data, args.id, args.status, args.note, args.target, ids)
        save(args.file, data)
        print(f"findings={len(data['findings'])}")
        return 0

    if args.cmd == "coverage":
        set_coverage(data, args.planned, args.done, args.skipped)
        save(args.file, data)
        print(json.dumps(data["coverage"], ensure_ascii=False))
        return 0

    if args.cmd == "done":
        ids = [x.strip() for x in (args.evidence or "").split(",") if x.strip()]
        add_done(data, args.id, ids, args.note)
        save(args.file, data)
        print(f"done={data['coverage']['done']}/{data['coverage'].get('planned') or '?'}")
        return 0

    if args.cmd == "reopen":
        reopen(data, args.reason)
        save(args.file, data)
        print("reopened -> running")
        return 0

    if args.cmd == "skip":
        add_skipped(data, args.id, args.reason)
        save(args.file, data)
        print(f"skipped={len(_skipped_items(data['coverage']))}")
        return 0

    if args.cmd == "verify":
        problems = verify(data)
        if not problems:
            print("OK: all delivery conditions met")
            return 0
        print("UNMET:")
        for p in problems:
            print("  -", p)
        return 1

    if args.cmd == "close":
        data = close(data)
        save(args.file, data)
        if data["unmet"]:
            print(f"NOT DELIVERED ({len(data['unmet'])} unmet):")
            for p in data["unmet"]:
                print("  -", p)
            return 1
        print("delivered")
        return 0

    if args.cmd == "show":
        summary = {
            "task": data.get("task"), "target": data.get("target"),
            "operation": data.get("operation"), "state": data.get("state"),
            "scope": data.get("scope"), "egress": data.get("egress"),
            "evidence": len(data.get("evidence", [])),
            "findings": [(f.get("id"), f.get("status")) for f in data.get("findings", [])],
            "coverage": data.get("coverage"), "unmet": data.get("unmet", []),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
