# Quarantined trusts, SID filtering, and the SDDL route

Companion to `cross-forest-trust-abuse/SKILL.md` Step 2b. Everything here is
about the case where Step 2 (SID-history golden ticket) is dead because the
trust enforces SID filtering, and you still need a usable path into forest B.

## 1. What the flags actually mean

Read the trust attributes from the trust object itself:

```bash
# from a domain-joined box, as any authenticated user
ldapsearch -H ldap://<dc-a> -Y GSSAPI -b "CN=System,DC=corp,DC=local" \
  "(objectClass=trustedDomain)" trustPartner trustDirection trustAttributes trustType
```

| Attribute bit | Name | Effect on you |
|---|---|---|
| `0x1` | `TRUST_ATTRIBUTE_NON_TRANSITIVE` | Only the trusted domain, no child domains. Enumerate child domains explicitly — the referral is absent, not empty. |
| `0x2` | `TRUST_ATTRIBUTE_UPLEVEL_ONLY` | Only Windows 2000+ semantics; legacy SID-history quirks do not apply. |
| `0x4` | `TRUST_ATTRIBUTE_QUARANTINED_DOMAIN` | **SID filtering ON.** Every `S-1-5-21-x-y-z-RID` from outside the trust is stripped from the PAC. Step 2 is dead. |
| `0x8` | `TRUST_ATTRIBUTE_FOREST_TRANSITIVE` | Cross-forest, both full forests. Referrals work; SID filtering still applies unless cleared. |
| `0x40` | `TRUST_ATTRIBUTE_CROSS_ORGANIZATION_NO_TGT_DELEGATION` | No TGT delegation across. Service-ticket tricks still fine. |
| `0x48` | `TREAT_AS_EXTERNAL` \| `FOREST_TRANSITIVE` | **Counts as quarantined** — `TREAT_AS_EXTERNAL` implies SID filtering. |
| `0x800` | `TRUST_ATTRIBUTE_CROSS_ORGANIZATION_ENABLE_TGT_DELEGATION` | TGT delegation allowed; unconstrained delegation chains reopen. |

Rule of thumb: `attr & 0x4` or `attr & 0x40` or `attr & 0x1` with an external
trust → assume filtering. Confirm empirically rather than trusting the map: a
forged extra SID comes back as "no rights", never as an error, so the only
reliable test is one benign extra SID (e.g. a group you can read) and a
rights check.

## 2. What survives SID filtering

SID filtering strips non-well-known SIDs *outside the trusted domain's own
domain SID*. These pass because they are in the well-known range or inside the
trusted domain:

| SID | Meaning | Why it survives |
|---|---|---|
| `S-1-5-32-544` | BUILTIN\Administrators | well-known, mapped locally on the B DC |
| `S-1-5-32-551` | BUILTIN\Backup Operators | well-known → SeBackupPrivilege on B DCs |
| `S-1-5-32-557` | BUILTIN\Incoming Forest Trust Builders | only meaningful in the trusting forest |
| `S-1-5-32-560` | BUILTIN\Windows Authorization Access Group | reads `tokenGroupsGlobalAndUniversal` |
| `S-1-5-32-562` | BUILTIN\Distributed COM Users | DCOM lateral into B |
| `S-1-5-9` | Enterprise Domain Controllers | survives **only** if the SID history really is EDC — do not fabricate |
| `S-1-5-11` | Authenticated Users | everyone already has it |
| `S-1-5-21-<B>-<rid>` | B's own domain SIDs | inside the trusted domain: **not** stripped |

The practical survivors are `32-544`, `32-551`, `32-557`, `32-560`, `32-562`
and B's own groups. `32-551` is the money one: SeBackupPrivilege on B's DC lets
you read `SAM`, `SYSTEM`, `SECURITY` — then DCSync or offline hash extraction.

## 3. Step 2b recipe — SDDL modification instead of SID history

When you cannot carry the SID, move the *permission* instead of the identity.

1. **Find a B-side object you can write.** You need a foothold in B first:
   - a service account in B whose password you own,
   - a B account you can reach via password reuse (same local-admin password),
   - a B machine account you control (unconstrained delegation host, or
     `ms-DS-MachineAccountQuota > 0` → add your own computer object).
2. **Confirm write on the object's DACL** (not just the object):

   ```bash
   # rights for your B identity on the target object
   impacket-dacledit -action read -target 'CN=DC01,OU=Domain Controllers,DC=b,DC=local' \
     -dc-ip <b-dc> 'b.local/svc:pass'
   ```

   Look for `WriteDacl` / `WriteOwner` / `GenericAll` / `GenericWrite`.
3. **Grant yourself the right** with an SDDL string, scoped to the target:

   ```bash
   # S-1-5-21-<B>-<your-rid> is inside B → allowed through the filter
   impacket-dacledit -action write -rights DCSync \
     -principal 'b\svc' -target-dn 'DC=b,DC=local' -dc-ip <b-dc> 'b.local/svc:pass'
   ```

   `-rights DCSync` expands to the two replication GUIDs
   (`1131f6aa-9c07-11d1-f79f-00c04fc2dcd2` and
   `1131f6ad-9c07-11d1-f79f-00c04fc2dcd2`).
4. **Replicate.** `impacket-secretsdump -just-dc -dc-ip <b-dc> 'b.local/svc:pass'`.
5. **Clean up** — restore the original SDDL you saved in step 2 (`-action restore`).
   A leftover DCSync ACE on the domain head is exactly what an IR team greps for.

Other writable-object finishes that do not need SID history:

- `WriteDacl` on a **GPO** linked at the domain root → push a startup script
  or a local-admin group add to every machine in B.
- `GenericWrite` on a **user** in B with an SPN → targeted Kerberoast (set the
  SPN yourself, request the ticket, crack offline). No cross-forest SID needed.
- `msDS-KeyCredentialLink` write (Shadow Credentials) on a B DC computer
  object → PKINIT as that DC, no password, no SID history.
- `GenericAll` on an **OU** → create a machine account, then RBCD onto a
  privileged host inside B.

## 4. ldap3 / impacket schema traps

These produce "no results" that look like permissions failures:

- **`objectSid` is binary on the wire.** ldap3 returns `bytes`; convert:

  ```python
  from ldap3.utils.conv import to_unicode
  sid = to_unicode(entry.objectSid.value)          # 'S-1-5-21-...'
  # or, without ldap3:
  import struct
  raw = entry.objectSid.value
  rev, cnt = raw[0], raw[1]
  auth = int.from_bytes(raw[2:8], "big")
  subs = [int.from_bytes(raw[8+4*i:12+4*i], "little") for i in range(cnt)]
  sid = f"S-1-{auth}-" + "-".join(map(str, subs))
  ```

- **`sIDHistory` needs a control.** It is a constructed attribute; request it
  with `ldap3` `search(..., attributes=['sIDHistory'])` on a DC, not on a
  Global Catalog unless you accept partial replicas.
- **Referrals:** the default `ldap3` connection does not chase referrals.
  Use `Server(host, get_info=ALL)` + `Connection(..., auto_referrals=True)` or
  query B's DC directly — chasing through the trust usually returns
  `referral` with an unauthenticated bind and then fails.
- **`foreignSecurityPrincipals` container** holds the *names* of cross-forest
  principals as `CN=<SID>,CN=ForeignSecurityPrincipals,DC=b,DC=local`. A
  foreign SID inside a home group is a named bridge account — resolve that RID
  in the child's user list before assuming it is a service account.
- **`adminCount=1`** does not mean privileged *now*; it means "was in a
  protected group once". Cross-check with `memberOf` before spending time.
- **GC vs DC ports:** `3268` (GC) only has partial attributes; `389` (DC) has
  everything but only for its own domain. Enumerate with 389 against each DC
  in B, then 3268 for cross-domain name resolution.

## 5. Failure signatures → what they really mean

| Signature | Real cause |
|---|---|
| Forged ticket accepted, rights unchanged | SID filtering stripped the extra SID (Step 2 on a quarantined trust) |
| `KRB_AP_ERR_MODIFIED` on forged TGT | fictitious RID on a 2025-hardened PAC, or wrong krbtgt key version |
| `KDC_ERR_WRONG_REALM` from impacket | impacket does not chase cross-realm referrals — use MIT `kvno` on the pivot |
| `STATUS_ACCESS_DENIED` on SAM read with SeBackupPrivilege | privilege not in token (filtered) or `FILE_OPEN_FOR_BACKUP_INTENT` not set (see `kerberos-trust-abuse/references/bkpintent_hook.py`) |
| LDAP returns 0 entries, bind succeeds | referral not followed, or you are querying a GC for a non-replicated attribute |
