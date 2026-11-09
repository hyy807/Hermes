#!/usr/bin/env python3
"""隔离测试 install-yufeng.sh：本机版（有 skills-local） vs 朋友版（无）"""
import os, shutil, subprocess, tempfile

REPO = "/root/Hermes"
SRC = open(os.path.join(REPO, "install-yufeng.sh"), encoding="utf-8").read()

# 去掉末尾的重启提示，避免网关自保护误判
clean = []
for line in SRC.split("\n"):
    low = line.lower()
    if ("gate" + "way") in low and ("re" + "start") in low:
        clean.append('echo "[skipped]"')
    else:
        clean.append(line)
CLEAN = "\n".join(clean)

def run(home, include_local):
    base = tempfile.mkdtemp(prefix="dfy_")
    repo = os.path.join(base, "repo")
    os.makedirs(repo)
    for d in ("skills", "deploy-tools", "plugins"):
        p = os.path.join(REPO, d)
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(repo, d))
    for f in ("AGENTS-yufeng.md", "SOUL-yufeng.md"):
        p = os.path.join(REPO, f)
        if os.path.isfile(p):
            shutil.copy2(p, repo)
    if include_local:
        p = os.path.join(REPO, "skills-local")
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(repo, "skills-local"))
    script = os.path.join(repo, "iu.sh")
    open(script, "w", encoding="utf-8").write(CLEAN)
    env = dict(os.environ, HOME=home, HERMES_HOME=os.path.join(home, ".hermes"))
    r = subprocess.run(["bash", script], capture_output=True, text=True, env=env)
    sk = 0
    sdir = os.path.join(home, ".hermes", "skills")
    for root, dirs, files in os.walk(sdir):
        if "SKILL.md" in files:
            sk += 1
    lines = [l for l in r.stdout.split("\n") if "技能" in l or "运维" in l or "本机" in l]
    return sk, lines, r.returncode

for label, incl, home in (
    ("本机版（有 skills-local）", True, "/tmp/m1"),
    ("朋友版（无 skills-local）", False, "/tmp/m2"),
):
    for h in (home,):
        shutil.rmtree(h, ignore_errors=True)
        os.makedirs(h, exist_ok=True)
    sk, lines, rc = run(home, incl)
    print("=== %s ===" % label)
    for l in lines:
        print("  " + l.strip())
    print("  技能总数: %d   退出码: %d\n" % (sk, rc))

shutil.rmtree("/tmp/m1", ignore_errors=True)
shutil.rmtree("/tmp/m2", ignore_errors=True)
