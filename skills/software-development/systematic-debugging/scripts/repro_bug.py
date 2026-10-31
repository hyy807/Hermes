#!/usr/bin/env python3
"""repro_bug.py — turn "it fails sometimes" into a number.

Phase 1 of systematic-debugging needs a reproduction RATE before anything else
is worth doing: a 50% flake is debuggable, a 1% flake usually is not.

Usage:
  scripts/repro_bug.py --cmd "pytest -x tests/test_x.py::test_y" --runs 100
  scripts/repro_bug.py --cmd "./bin/app --input poc" --runs 50 --jobs 8 --timeout 20
  scripts/repro_bug.py --cmd "pytest tests/test_x.py" --runs 200 --stress --json out.json

Output: pass/fail counts, failure rate, first failing stderr, and (with
--stress) whether adding load changes the rate. Exit 0 if the failure rate is
stable and > 0 (reproducible), 1 if 0% (bug not reproduced), 2 on usage error.

--jobs>1 runs concurrently; that changes timing, so treat the number as
"reproduction rate under load", not the baseline. Run serial first.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor


def one(cmd, timeout, env):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return {"rc": p.returncode, "secs": round(time.time() - t0, 3),
                "tail": (p.stderr or p.stdout)[-1500:], "timeout": False}
    except subprocess.TimeoutExpired:
        return {"rc": -9, "secs": round(time.time() - t0, 3), "tail": "TIMEOUT", "timeout": True}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="command that reproduces (shell string)")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--expect", type=int, default=0, help="exit code meaning PASS (default 0)")
    ap.add_argument("--stress", action="store_true", help="also run with CPU load to widen timing windows")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    if a.runs < 1:
        sys.stderr.write("error: --runs must be >= 1\n")
        return 2
    cmd = shlex.split(a.cmd)
    env = dict(os.environ)
    if shell_needed(cmd):
        cmd = ["bash", "-c", a.cmd]

    print(f"== repro_bug: {' '.join(cmd)}  runs={a.runs} jobs={a.jobs} ==")
    results = execute(cmd, a.runs, a.jobs, a.timeout, env)
    rate = report(results, a.expect)

    if a.stress:
        print("\n== stressed run (same command, CPU contention) ==")
        stop = start_load()
        try:
            r2 = execute(cmd, a.runs, a.jobs, a.timeout, env)
        finally:
            stop()
        rate2 = report(r2, a.expect)
        print(f"\nstress delta: {rate:.1%} -> {rate2:.1%} "
              f"({'widened' if rate2 > rate else 'unchanged/narrowed'})")
        results.extend(r2)

    payload = {"cmd": a.cmd, "runs": len(results),
               "fail": sum(1 for r in results if r["rc"] != a.expect),
               "rate": rate, "results": results[:20]}
    if a.json:
        with open(a.json, "w") as f:
            json.dump(payload, f, indent=1)
        print(f"json: {a.json}")

    if rate == 0.0:
        print("\nVERDICT: 0% reproduction — not a bug you can chase yet. "
              "Widen the trigger (input variant, timing, concurrency, env) before Phase 2.")
        return 1
    if rate >= 1.0:
        print("\nVERDICT: 100% deterministic — go straight to root-cause (Phase 2), "
              "no need for instrumentation loops.")
    else:
        print(f"\nVERDICT: reproducible at {rate:.1%} — instrument now; fix must make this 0%.")
    return 0


def shell_needed(argv):
    """A quoted --cmd with pipes/redirects must go through a shell."""
    return any(ch in " ".join(argv) for ch in "|&;><$`")


def execute(cmd, runs, jobs, timeout, env):
    out = []
    if jobs <= 1:
        for i in range(1, runs + 1):
            r = one(cmd, timeout, env)
            r["n"] = i
            out.append(r)
            if i % 10 == 0 or i == runs:
                print(f"  {i}/{runs}", flush=True)
        return out
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(one, cmd, timeout, env) for _ in range(runs)]
        for i, fu in enumerate(futs, 1):
            r = fu.result()
            r["n"] = i
            out.append(r)
    return out


def report(results, expect):
    fail = [r for r in results if r["rc"] != expect]
    rate = len(fail) / len(results) if results else 0.0
    print(f"pass={len(results)-len(fail)} fail={len(fail)} rate={rate:.1%} "
          f"avg={sum(r['secs'] for r in results)/len(results):.2f}s")
    if fail:
        print("first failure stderr (tail):")
        print("\n".join("   " + l for l in fail[0]["tail"].splitlines()[-8:]))
        codes = sorted({r["rc"] for r in fail})
        print(f"failure exit codes: {codes}")
    return rate


def start_load():
    procs = []
    n = os.cpu_count() or 1
    for _ in range(max(1, n - 1)):
        procs.append(subprocess.Popen(["bash", "-c", "while :; do :; done"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def stop():
        for p in procs:
            p.kill()
    return stop


if __name__ == "__main__":
    sys.exit(main())
