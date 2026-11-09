#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开工自检（kickoff）
===================
收到新目标时先跑这个，把「该用什么技能」和「以前打没打过」一次性摆出来。

用法：
    python3 /root/pentest/kickoff.py example.com
    python3 /root/pentest/kickoff.py example.com 饿饭 饿饭云     # 带别名

输出三段：
  1. 技能匹配      —— 按关键词命中技能库里的 name / description / 正文
  2. 历史产物      —— scratch 里文件名或内容含该关键词的目录/文件
  3. 结论          —— 打过 / 没打过，建议动作

退出码：0 = 没打过（按新目标走）；1 = 打过（复用旧链路）
"""
import os
import re
import sys
import json

SKILLS = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "skills")
SCRATCH = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "cache", "scratch")
APKS = os.path.expanduser("~/apks")
MEMORY = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
                      "memories", "MEMORY.md")

# 技能名/描述里出现这些词，说明跟安全渗透相关；用来给结果排序
SEC_HINTS = ("pentest", "security", "hunt", "exploit", "recon", "assessment",
             "scan", "waf", "bypass", "credential", "proxy", "reverse", "audit")


# 太通用的词，不能当关键词用（否则满库乱命中）
STOPWORDS = {
    "live", "www", "api", "app", "web", "mail", "cdn", "static", "img",
    "admin", "panel", "login", "auth", "user", "www2", "m", "wap", "v2",
    "cloud", "server", "node", "test", "dev", "prod", "new", "old", "home",
    "com", "cn", "net", "org", "io", "me", "cc", "xyz", "top", "site",
    # 保留域名 / 示例域名，不能当目标
    "example.com", "example.org", "example.net", "test.com", "localhost",
    "domain.com", "site.com", "foo.com", "bar.com",
    "example", "sample", "demo", "dummy", "target", "host", "domain",
}

# 正文里出现域名级别的命中，权重比普通词高（说明是真记录而不是泛泛提及）
def kw_weight(k):
    return 6 if "." in k else 1


def keywords(target, aliases):
    """从目标里切出用于搜索的关键词"""
    t = target.strip().lower()
    t = re.sub(r"^https?://", "", t)
    t = re.sub(r"/.*$", "", t)
    parts = {t}
    labels = t.split(".")
    parts.add(labels[0])                        # 主域名
    if len(labels) >= 2:
        parts.add(".".join(labels[-2:]))        # 顶级两段
    for a in aliases:
        a = a.strip()
        if a:
            parts.add(a.lower())
    return sorted({p for p in parts
                   if len(p) >= 4 and p not in STOPWORDS},
                  key=len, reverse=True)


def scan_skills(kws):
    """扫技能库，返回命中的技能。名称 > 描述 > 正文，正文单独命中权重很低"""
    hits = {}
    for root, dirs, files in os.walk(SKILLS):
        if "SKILL.md" not in files:
            continue
        path = os.path.join(root, "SKILL.md")
        name = os.path.basename(root).lower()
        try:
            body = open(path, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        low = body.lower()
        # 抽出 frontmatter 里的 description
        m = re.search(r"^description:\s*(.+)$", body, re.M)
        desc = (m.group(1) if m else "").lower()
        score, where = 0, []
        for k in kws:
            if k in name:
                score += 30
                where.append("名称")
            if k in desc:
                score += 15
                where.append("描述")
            n = low.count(k)
            if n:
                score += min(n * kw_weight(k), 20)
                where.append("正文×%d" % n)
        if score:
            hits[name] = {"path": path, "score": score,
                          "where": ",".join(dict.fromkeys(where)),
                          "desc": extract_desc(body)}
    # 只留分数像样的，名称/描述命中优先
    return sorted(((n, i) for n, i in hits.items() if i["score"] >= 3),
                  key=lambda x: -x[1]["score"])


def extract_desc(body):
    m = re.search(r"^description:\s*(.+)$", body, re.M)
    if not m:
        return ""
    d = m.group(1).strip().strip('"').strip("'")
    return d[:95]


def scan_dirs(kws, base, label, max_hits=12):
    """扫目录，看文件名/目录名/文本内容有没有命中"""
    if not os.path.isdir(base):
        return []
    out = []
    for root, dirs, files in os.walk(base):
        depth = root[len(base):].count(os.sep)
        if depth > 3:
            dirs[:] = []
            continue
        for k in kws:
            if k in root.lower():
                out.append(("目录", root))
                break
        for f in files:
            lowf = f.lower()
            if any(k in lowf for k in kws):
                p = os.path.join(root, f)
                try:
                    sz = os.path.getsize(p)
                except Exception:
                    sz = 0
                out.append((label, "%s  (%d B)" % (p, sz)))
    # 去重
    seen, uniq = set(), []
    for tag, p in out:
        if p not in seen:
            seen.add(p)
            uniq.append((tag, p))
    return uniq[:max_hits]


def scan_text(kws, base, label, max_hits=8):
    """在目录里的文本文件内容里找关键词（只扫小文件）"""
    if not os.path.isdir(base):
        return []
    out = []
    exts = (".md", ".txt", ".json", ".py", ".yml", ".yaml", ".sh")
    for root, dirs, files in os.walk(base):
        depth = root[len(base):].count(os.sep)
        if depth > 2:
            dirs[:] = []
            continue
        for f in files:
            if not f.lower().endswith(exts):
                continue
            p = os.path.join(root, f)
            try:
                if os.path.getsize(p) > 2_000_000:
                    continue
                txt = open(p, encoding="utf-8", errors="ignore").read().lower()
            except Exception:
                continue
            if any(k in txt for k in kws):
                out.append((label, p))
                if len(out) >= max_hits:
                    return out
    return out


def scan_memory(kws):
    if not os.path.exists(MEMORY):
        return []
    try:
        txt = open(MEMORY, encoding="utf-8", errors="ignore").read()
    except Exception:
        return []
    low = txt.lower()
    return [k for k in kws if k in low]


def _write_contract(target, path):
    """开一个 draft 契约，让本次任务的 scope/egress/交付物有地方落。"""
    import subprocess
    repo = os.environ.get("HERMESYF_REPO", "/root/Hermes")
    try:
        subprocess.run([sys.executable, "-m", "yf_tools.task_contract", "new",
                        "--target", target, "-o", path],
                       cwd=repo, check=True, capture_output=True, text=True, timeout=30)
        subprocess.run([sys.executable, "-m", "yf_tools.task_contract", "set", path,
                        "--scope", target],
                       cwd=repo, check=True, capture_output=True, text=True, timeout=30)
        print("  → 任务契约：%s（draft；补 egress/交付物后 state ready）" % path)
    except Exception as exc:
        print("  → 契约生成跳过：%s" % exc)


def main():
    argv = sys.argv[1:]
    contract = None
    if "--contract" in argv:
        i = argv.index("--contract")
        if i + 1 >= len(argv):
            sys.exit("--contract 需要一个输出路径")
        contract = argv[i + 1]
        del argv[i:i + 2]
    rc = _main_impl(argv)
    if contract and argv:
        _write_contract(argv[0], contract)
    return rc


def _main_impl(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 1:
        sys.exit("用法: kickoff.py <目标域名或站名> [别名1] [别名2] ... [--contract 路径]")
    target = argv[0]
    aliases = argv[1:]
    kws = keywords(target, aliases)

    if not kws:
        print("=" * 72)
        print("开工自检  target=%s" % target)
        print("=" * 72)
        print("\n关键词全被过滤（保留域名 / 示例域名 / 太通用的词）")
        print("→ 当成新目标处理：直接侦察，打完记得落盘")
        print("=" * 72)
        return 0

    print("=" * 72)
    print("开工自检  target=%s" % target)
    print("关键词    %s" % ", ".join(kws))
    print("=" * 72)

    # 1. 技能
    print("\n【1】技能匹配")
    sk = scan_skills(kws)
    if sk:
        for name, info in sk[:10]:
            star = "★" if info["score"] >= 10 else "·"
            print("  %s %-38s [%s] %s" % (star, name, info["where"], info["desc"]))
        print("\n  → 命中 %d 个，优先加载得分最高的：skill_view(name='%s')" % (len(sk), sk[0][0]))
    else:
        print("  无命中 —— 技能库没有对应打法，按通用流程走")

    # 2. 历史产物
    print("\n【2】历史产物")
    total = 0
    for base, label in ((SCRATCH, "scratch"), (APKS, "apks")):
        named = scan_dirs(kws, base, label)
        if named:
            print("  %s/" % base)
            for tag, p in named:
                print("    %-6s %s" % (tag, p))
            total += len(named)
        inner = scan_text(kws, base, label)
        if inner:
            seen = {p for _, p in named}
            extra = [(t, p) for t, p in inner if p not in seen]
            if extra:
                print("    内容命中：")
                for tag, p in extra:
                    print("      %-6s %s" % (tag, p))
                total += len(extra)
    if not total:
        print("  scratch / apks 里没有这个目标的痕迹")

    # 3. 记忆
    print("\n【3】MEMORY 索引")
    mh = scan_memory(kws)
    print("  %s" % ("命中: " + ", ".join(mh) if mh else "未命中"))

    # 4. 结论
    print("\n" + "=" * 72)
    if total or sk or mh:
        print("结论：这个目标有历史痕迹 / 有对应技能")
        if total:
            print("  → 先读上面列出的产物，复用已验证的链路，只补缺的部分")
        if sk:
            print("  → 动手前先 skill_view(name='%s')" % sk[0][0])
        if mh:
            print("  → MEMORY 里记过这个目标（%s），结论可能还在，但 evidence 路径要自己核实" % ", ".join(mh))
        print("  → 别忘了 session_search(query='%s') 补会话历史" % " ".join(kws[:2]))
        print("=" * 72)
        return 1
    # 索引没命中 ≠ 从未做过：scratch 会过期、技能可能改名、会话历史不在索引里。
    print("结论：本次索引没找到痕迹")
    print("  → 先用 session_search 查会话历史，再按标准侦察流程走")
    print("  → 打完记得落盘（技能 + MEMORY + 脚本）")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
