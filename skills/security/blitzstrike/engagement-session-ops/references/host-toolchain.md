# Host toolchain inventory — worked example

The point of this file: **one command, before hunting**, so you never discover
mid-chain that the tool you needed was never installed. Paths differ per host;
the format is what matters. Run it in the first two minutes of an engagement.

## The one-shot inventory

```bash
{
  echo "== host =="; uname -a; id; cat /etc/os-release | head -2
  echo "== paths =="; echo "$PATH" | tr ':' '\n'
  echo "== bins =="
  for b in nmap masscan rustscan naabu httpx nuclei subfinder ffuf feroxbuster \
           gobuster sqlmap nikto hydra sshpass proxychains4 chisel socat \
           netexec nxc crackmapexec impacket-secretsdump impacket-getTGT \
           impacket-ticketer bloodhound-python bloodyAD certipy ldapsearch \
           enum4linux-ng smbclient rpcclient evil-winrm wmiexec.py \
           responder mitm6 hashcat john tcpdump tshark; do
    p=$(command -v "$b" 2>/dev/null) && printf '%-28s %s\n' "$b" "$p"
  done
  echo "== python =="; for p in python3 python; do command -v $p && $p -V; done
  python3 - <<'PY' 2>/dev/null
mods = ["impacket","ldap3","pypsrp","requests","pwn","dnspython","pyasn1","cryptography"]
for m in mods:
    try:
        mod = __import__(m); print(f"  py:{m:14s} {getattr(mod,'__version__','?')}")
    except Exception: pass
PY
  echo "== wordlists =="; ls -la /usr/share/wordlists 2>/dev/null | head
  echo "== go =="; ls ~/go/bin 2>/dev/null | tr '\n' ' '; echo
} 2>/dev/null | tee toolchain.txt
```

## What a real box looks like (annotated output)

```text
== host ==
Linux pivot 6.1.0-13-amd64 #1 SMP Debian 6.1.55-1 x86_64 GNU/Linux
uid=0(root) gid=0(root) groups=0(root)          # root → SYN scans + tcpdump OK

== paths ==
/root/.local/bin:/root/go/bin:/usr/local/bin:/usr/bin:/bin
                     ^^^^^^^^^^ go installs land here, NOT in /usr/local/bin
== bins ==
nmap                         /usr/bin/nmap
masscan                      /usr/bin/masscan
naabu                        /root/go/bin/naabu            # PATH-dependent
nuclei                       /root/go/bin/nuclei
httpx                        /root/go/bin/httpx
netexec                      /usr/bin/nxc                  # binary renamed; `nxc` works, `netexec` does not
impacket-secretsdump         /usr/bin/impacket-secretsdump # apt impacket: called as impacket-*, module names differ from pip
bloodyAD                     /usr/bin/bloodyAD
certipy                      /usr/bin/certipy
ldapsearch                   /usr/bin/ldapsearch
smbclient                    /usr/bin/smbclient
chisel                       /root/.local/bin/chisel
== python ==
/usr/bin/python3  3.11.2                        # system python: NO pip module on Debian 12 (PEP 668)
  py:impacket   0.11.0
  py:ldap3      2.9.1
  py:pypsrp     0.8.0
== wordlists ==
drwxr-xr-x 2 root root 4096 /usr/share/wordlists     # empty dir: DirBuster lists are in /usr/share/dirb, rockyou in /usr/share/wordlists/rockyou.txt.gz
== go ==
naabu httpx nuclei subfinder ffuf
```

## Failure modes this inventory is designed to catch

| Trap | What it looks like | Fix |
|---|---|---|
| `go install` shadowed | `nuclei: command not found` from a script, but works in your shell | add `~/go/bin` to PATH **inside** the script/cron, or symlink into `/usr/local/bin` |
| apt impacket vs pip impacket | `impacket-secretsdump` exists but `python3 -c 'import impacket'` fails (or vice versa, older version) | check `python3 -c "import impacket;print(impacket.__file__)"`; the CLI wrapper and the library can be different versions |
| PEP 668 system python | `pip install X` → `error: externally-managed-environment` | `python3 -m venv /opt/pt && /opt/pt/bin/pip install ...`; then call `/opt/pt/bin/python -m ...` explicitly |
| `netexec` vs `nxc` | apt package ships `nxc` (Debian renames for trademark) | symlink or use `nxc` |
| Missing 32-bit libs | `hashcat` refuses `-m 1000` on a stripped host | `dpkg --add-architecture i386` only if you actually need kernel-mode; CPU mode is fine for most NTLM |
| No wordlists | `ls /usr/share/wordlists` empty (kali-only package) | fetch rockyou separately; check `/usr/share/dirb/wordlists`, `/usr/share/seclists` |
| DNS resolves but tools fail | `getent hosts dc` works, `nxc` fails | the box may use systemd-resolved stub `127.0.0.53`; tools that open their own resolver ignore it — pass `-d <real dns>` |
| Rootless container | `id` says `uid=0` inside, but no `NET_RAW` | SYN scan fails with `Permission denied`; fall back to `-sT`, and `tcpdump` needs `--cap-add=NET_RAW` |
| Clock | no `chrony`/`ntp` running | meter skew before every Kerberos op (`kerberos-trust-abuse/references/smb2time.py`) |

## Rules

- **Inventory once, save it.** `toolchain.txt` goes in the workdir; on resume
  you diff it instead of re-probing.
- **Verify the version you will actually invoke**, not the newest one on disk
  (`nmap --version`, `python3 -c 'import impacket;print(impacket.__version__)'`).
- **A missing tool is not a blocker** unless it is the only path: note it in
  `STATE.md` and pick the next vector.
- **Do not install mid-engagement** on a target host you do not own — every
  package manager call writes to disk, touches the network, and leaves a log.
  Ship static binaries (chisel, naabu, chisel-served impacket venv) instead.
