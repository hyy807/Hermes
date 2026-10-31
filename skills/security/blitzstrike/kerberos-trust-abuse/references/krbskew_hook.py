#!/usr/bin/env python3
"""krbskew_hook.py — KRB_SKEW-gated local timestamp shift for Kerberos tooling.

When your box is minutes off the KDC and you cannot change the clock (no root,
container, managed host), shift what the *tooling* sees instead. This hook
patches time.time()/time.gmtime-related surfaces for the impacket/MIT krb5
client path so ticket timestamps land inside the KDC's window.

Install (must be a .pth — sitecustomize.py is shadowed by the distro python):

    python3 -c "import site,sys;print(site.getsitepackages()[0])"
    echo "import krbskew_hook" > <site-packages>/krbskew.pth
    cp references/krbskew_hook.py <site-packages>/

Usage:

    KRB_SKEW=-312 python3 -c 'import krbskew_hook; import time; print(time.time())'
    KRB_SKEW=+95  impacket-getTGT -dc-ip 10.10.10.5 corp.local/user:pass
    ENV:  KRB_SKEW   seconds to ADD to the local clock (negative = go back)
          KRB_SKEW_DBG=1  log every patched call site

Scope: process-wide, opt-in, and a no-op when KRB_SKEW is unset. It does NOT
change the system clock, so RTT-based measurements (SMB2 meter, network timing)
stay honest — it only shifts what library code reads as "now".

Measure the skew first with references/smb2time.py; guessing the offset wastes
more time than measuring it.
"""
from __future__ import annotations

import os
import time as _time

_OFFSET = float(os.environ.get("KRB_SKEW", "0") or 0)
_DEBUG = os.environ.get("KRB_SKEW_DBG", "") not in ("", "0")
_installed = False


def _log(what: str) -> None:
    if _DEBUG:
        import sys
        sys.stderr.write(f"[krbskew] {what}\n")


class _ShiftedDatetime:
    """Proxy for datetime.datetime with utcnow()/now() shifted by _OFFSET."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def utcnow(self, *a, **k):
        _log("datetime.utcnow")
        return self._real.utcfromtimestamp(_time.time())

    def now(self, tz=None):
        _log("datetime.now")
        if tz is None:
            return self._real.fromtimestamp(_time.time())
        return self._real.now(tz)


def install(offset: float | None = None) -> float:
    """Patch time.time / time.time_ns. Idempotent. Returns applied offset."""
    global _OFFSET, _installed
    if offset is not None:
        _OFFSET = float(offset)
    if _installed:
        return _OFFSET
    if _OFFSET == 0:
        _log("offset 0 — hook loaded but inactive")
        return 0.0

    real_time = _time.time
    real_time_ns = getattr(_time, "time_ns", None)

    def shifted_time():
        _log("time.time")
        return real_time() + _OFFSET

    _time.time = shifted_time
    if real_time_ns is not None:
        _rns = real_time_ns

        def shifted_time_ns():
            _log("time.time_ns")
            return _rns() + int(_OFFSET * 1e9)

        _time.time_ns = shifted_time_ns

    # time.localtime/gmtime take an optional timestamp; ticket code usually
    # calls them with no argument, which then reads the patched time.time().
    import datetime as _dt

    class _DT(_dt.datetime):
        @classmethod
        def utcnow(cls):
            _log("datetime.datetime.utcnow")
            return _dt.datetime.utcfromtimestamp(_time.time())

        @classmethod
        def now(cls, tz=None):
            _log("datetime.datetime.now")
            if tz is None:
                return _dt.datetime.fromtimestamp(_time.time())
            return _dt.datetime.now(tz)

    _dt.datetime = _DT  # type: ignore[misc]
    _installed = True
    _log(f"installed offset={_OFFSET:+.1f}s")
    return _OFFSET


def uninstall() -> None:
    """Best-effort revert (only useful in tests; a fresh process is cleaner)."""
    global _installed
    if not _installed:
        return
    import importlib
    importlib.reload(_time)
    _installed = False


if __name__ == "__main__":
    applied = install()
    print(f"offset={applied:+.1f}s  time.time()={_time.time():.0f}  "
          f"delta_visible={applied:+.1f}")
