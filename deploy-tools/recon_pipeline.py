#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""信息收集流水线：一条命令跑完 子域 → 存活 → 指纹 → 端口。

为什么要有这个：以前"先收集信息"是一句提示，模型每次凭记忆拼命令，顺序和参数都不稳定，
产物散在各处，下次还要重新拼。这里把顺序、去重、归档、契约登记全部钉死。

用法
  python3 recon_pipeline.py -d example.com                          # 子域+存活+指纹
  python3 recon_pipeline.py -d example.com --ports                  # 再加端口扫描（top100）
  python3 recon_pipeline.py -d example.com --contract <契约.json>    # 产物自动登记进任务契约
  python3 recon_pipeline.py -d example.com --skip-sub   # 已经有一批子域时跳过 subfinder

产物（默认 /root/apks/recon/<domain>/）
  subs.txt       subfinder 原始输出
  hosts.txt      去重后的全部主机（含主域）
  live.jsonl     httpx 逐行 JSON（状态码/标题/技术栈/CDN）
  live.txt       存活 URL 清单
  tech.txt       技术栈汇总（出现次数排序）
  ports.txt      端口（--ports 时）
  summary.json   统计 + 生成时间 + 工具版本

全部走 mihomo（默认 127.0.0.1:7890），可用 --proxy 覆盖，--no-proxy 关掉。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

GOBIN = Path("/root/go/bin")
RECON_BASE = Path(os.environ.get("HERMES_RECON_BASE", "/root/apks/recon"))
DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


def _clean_domain(raw: str) -> str:
    """只接受域名或 IPv4。目标字符串会进路径，`../..` 之类必须在这里挡住。"""
    d = (raw or "").strip().rstrip(".").lower()
    if not d or len(d) > 253:
        raise SystemExit(f"域名不合法: {raw!r}")
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", d):
        return d
    if not DOMAIN_RE.match(d) or ".." in d:
        raise SystemExit(f"域名不合法: {raw!r}（只接受 a.b.c 形式或 IPv4）")
    return d


def _norm_egress(value: str) -> str:
    v = (value or "").strip().lower()
    for pre in ("http://", "https://", "socks5://", "socks5h://"):
        if v.startswith(pre):
            v = v[len(pre):]
    return v.rstrip("/")


def tool(name: str) -> str | None:
    p = shutil.which(name) or (str(GOBIN / name) if (GOBIN / name).exists() else None)
    return p


def run(cmd: list[str], timeout: int, env: dict | None = None, quiet: bool = True) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **(env or {})})
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout {timeout}s"
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-d", "--domain", required=True)
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--contract", default="")
    ap.add_argument("--ports", action="store_true", help="跑 naabu top100")
    ap.add_argument("--skip-sub", action="store_true", help="跳过 subfinder（已有 subs.txt 时）")
    ap.add_argument("--proxy", default="http://127.0.0.1:7890")
    ap.add_argument("--socks5", default="", help="naabu 专用 socks5（如 socks5://127.0.0.1:7891）；不给则 --ports 拒绝执行")
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--allow-outside", action="store_true",
                    help="允许 --out 落在 ~/apks/recon 之外（只给测试用，契约场景别开）")
    ap.add_argument("--timeout", type=int, default=600, help="单步超时秒")
    args = ap.parse_args()

    domain = _clean_domain(args.domain)

    if args.contract and args.allow_outside:
        raise SystemExit("契约场景不允许 --allow-outside（产物必须在受保护目录内）")
    outdir = Path(args.out or (RECON_BASE / domain)).resolve()
    base = RECON_BASE.resolve()
    if not args.allow_outside and base not in outdir.parents and outdir != base:
        raise SystemExit(f"--out 必须在 {base} 之内（防路径穿越）: {outdir}")

    proxy = "" if args.no_proxy else args.proxy

    # 契约是硬约束：侦察不能绕开任务范围、出口和禁打清单
    if args.contract:
        try:
            cdata = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        except Exception as exc:
            raise SystemExit(f"契约读不了: {exc}")
        st = str(cdata.get("state") or "")
        if st not in ("ready", "running"):
            raise SystemExit(f"契约 state={st!r}，只有 ready/running 可以执行")
        c_egress = str(cdata.get("egress") or "").strip()
        if not c_egress:
            raise SystemExit("契约没写 egress，拒绝执行")
        if args.no_proxy:
            raise SystemExit("契约要求走代理，--no-proxy 与契约冲突，拒绝执行")
        if _norm_egress(args.proxy) != _norm_egress(c_egress):
            raise SystemExit(f"--proxy {args.proxy} 与契约 egress {c_egress} 不一致，拒绝执行")
        c_socks = str(cdata.get("egress_socks5") or "").strip()
        if args.ports:
            # 端口扫描是唯一用 socks5 的步骤：只校验主机不够，同机两个实例照样换出口
            if not c_socks:
                raise SystemExit(
                    "契约未声明 egress_socks5，--ports 拒绝执行"
                    "（无法证明 naabu 走契约出口，先在契约里写 egress_socks5）")
            if _norm_egress(args.socks5) != _norm_egress(c_socks):
                raise SystemExit(
                    f"--socks5 {args.socks5} 与契约 egress_socks5 {c_socks} 不一致，拒绝执行")
        elif args.socks5:
            s_host = _norm_egress(args.socks5).rsplit(":", 1)[0]
            e_host = _norm_egress(c_egress).rsplit(":", 1)[0]
            if s_host != e_host:
                raise SystemExit(
                    f"--socks5 {args.socks5} 与契约 egress {c_egress} 不是同一个出口主机，拒绝执行")
        forbidden = [str(x).strip().lower() for x in (cdata.get("forbidden") or []) if str(x).strip()]
        for f in forbidden:
            if domain == f or domain.endswith("." + f.lstrip("*.")):
                raise SystemExit(f"{domain} 命中契约 forbidden: {f}")
        try:
            sys.path.insert(0, os.environ.get("HERMESYF_REPO", "/root/Hermes"))
            from yf_tools.assessment_run import _target_allowed
        except Exception as exc:
            # 范围校验器加载不了就一个包都不发：宁可停，也不能在没校验范围的情况下扫
            raise SystemExit(f"无法加载范围校验器，拒绝执行: {exc}")
        scope = cdata.get("scope") or []
        if not scope:
            raise SystemExit("契约没有 scope，拒绝执行")
        if not _target_allowed(domain, scope):
            raise SystemExit(f"{domain} 不在契约 scope 内: {scope}")

    outdir.mkdir(parents=True, exist_ok=True)

    summary: dict = {"domain": domain, "started": datetime.now().isoformat(timespec="seconds"),
                     "steps": {}, "tools": {}, "errors": []}
    errors: list[str] = summary["errors"]

    def fail(msg: str) -> None:
        errors.append(msg)
        print(f"  !! {msg}")

    def note(step: str, **kw):
        summary["steps"][step] = kw
        print(f"  [{step}] " + "  ".join(f"{k}={v}" for k, v in kw.items()))

    print(f"=== recon {domain} → {outdir} ===")

    # 1. 子域
    subs: list[str] = []
    subs_file = outdir / "subs.txt"
    if not args.skip_sub:
        sf = tool("subfinder")
        if not sf:
            fail("subfinder 缺失，跳过子域枚举（后续只有主域）")
            note("subdomains", count=0, error="subfinder missing")
        else:
            env = {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy} if proxy else {}
            rc, so, se = run([sf, "-d", domain, "-all", "-silent", "-timeout", "10"], args.timeout, env)
            subs = sorted({l.strip().lower() for l in so.splitlines() if l.strip()})
            subs_file.write_text("\n".join(subs) + ("\n" if subs else ""), encoding="utf-8")
            if rc != 0:
                fail(f"subfinder 退出码 {rc}: {se.strip().splitlines()[-1][:80] if se.strip() else ''}")
            note("subdomains", count=len(subs), rc=rc, err=se.strip().splitlines()[-1][:80] if se.strip() else "")
    elif subs_file.is_file():
        subs = [l.strip() for l in subs_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        note("subdomains", count=len(subs), source="cached")

    hosts = sorted(set(subs) | {domain})
    (outdir / "hosts.txt").write_text("\n".join(hosts) + "\n", encoding="utf-8")
    note("hosts", total=len(hosts))

    # 2/3. 存活 + 指纹
    hx = tool("httpx")
    live: list[dict] = []
    if not hx:
        fail("httpx 缺失，无法做存活探测")
        note("live", count=0, error="httpx missing")
    else:
        cmd = [hx, "-l", str(outdir / "hosts.txt"), "-silent", "-json",
               "-status-code", "-title", "-tech-detect", "-ip", "-cname",
               "-threads", "50", "-timeout", "8", "-retries", "1"]
        if proxy:
            cmd += ["-http-proxy", proxy]
        rc, so, se = run(cmd, args.timeout)
        for line in so.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                live.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        (outdir / "live.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in live),
                                           encoding="utf-8")
        urls = sorted({x.get("url") or x.get("input", "") for x in live if x.get("url") or x.get("input")})
        (outdir / "live.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")
        tech = Counter()
        for x in live:
            for t in (x.get("tech") or []):
                tech[t] += 1
        (outdir / "tech.txt").write_text(
            "\n".join(f"{t}\t{n}" for t, n in tech.most_common()) + ("\n" if tech else ""), encoding="utf-8")
        codes = Counter(str(x.get("status_code")) for x in live)
        if rc != 0:
            fail(f"httpx 退出码 {rc}: {se.strip().splitlines()[-1][:80] if se.strip() else ''}")
        elif not live:
            fail("httpx 没有任何存活结果（0 行）—— 可能全站挂了，也可能参数/代理不对")
        note("live", count=len(live), codes=dict(codes.most_common(6)),
             techs=len(tech), rc=rc,
             err=se.strip().splitlines()[-1][:80] if se.strip() else "")

    # 4. 端口（可选）
    if args.ports:
        nb = tool("naabu")
        if not nb:
            fail("naabu 缺失，跳过端口扫描")
            note("ports", error="naabu missing")
        elif not args.socks5:
            # 以前把 http://…:7890 硬替换成 socks5://…:7891，纯靠猜端口：
            # 自定义代理时映射错、7891 没监听时 naabu 可能裸连。
            fail("--ports 需要显式 --socks5（不猜端口映射），已跳过端口扫描")
            note("ports", error="socks5 not specified")
        else:
            cmd = [nb, "-list", str(outdir / "hosts.txt"), "-top-ports", "100", "-silent",
                   "-rate", "500", "-timeout", "1500"]
            cmd += ["-proxy", args.socks5]
            rc, so, se = run(cmd, args.timeout)
            (outdir / "ports.txt").write_text(so, encoding="utf-8")
            note("ports", lines=len(so.splitlines()), rc=rc,
                 err=se.strip().splitlines()[-1][:80] if se.strip() else "")

    # 5. 收尾
    summary["finished"] = datetime.now().isoformat(timespec="seconds")
    for t in ("subfinder", "httpx", "nuclei", "naabu"):
        p = tool(t)
        if p:
            rc, so, _ = run([p, "-version"], 10)
            summary["tools"][t] = (so.splitlines()[0][:60] if so else "installed")
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n产物目录 {outdir}")
    for f in sorted(outdir.iterdir()):
        print(f"  {f.name:<14} {f.stat().st_size:>10,} B")
    if errors:
        print(f"\n!! {len(errors)} 个错误（侦察不完整，不要当成已完成）")
        for e in errors:
            print("   -", e)

    # 6. 登记进任务契约（可选）
    if args.contract:
        repo = os.environ.get("HERMESYF_REPO", "/root/Hermes")
        registered, failed_reg = 0, []
        for f in ("live.jsonl", "live.txt", "tech.txt", "hosts.txt", "summary.json"):
            fp = outdir / f
            if not fp.is_file():
                continue
            pr = subprocess.run([sys.executable, "-m", "yf_tools.task_contract", "evidence",
                                 args.contract, "--path", str(fp), "--kind", "recon"],
                                cwd=repo, capture_output=True, text=True, timeout=30)
            if pr.returncode == 0:
                registered += 1
            else:
                failed_reg.append(f"{f}: {(pr.stderr or '').strip()[:80]}")
        if failed_reg:
            fail("契约登记失败: " + "; ".join(failed_reg))
            print(f"登记 {registered} 个，失败 {len(failed_reg)} 个")
        else:
            print(f"已登记进契约（{registered} 个文件）: {args.contract}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
