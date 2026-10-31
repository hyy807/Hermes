# Finding report template

Copy this file into the engagement workdir and fill it in. One document per
engagement. Delete sections that do not apply — a template with empty headers
reads like a copy-paste job.

````markdown
# <Client / project> — security assessment report

- **Scope:** <domains / IP ranges / repos, exactly as agreed>
- **Window:** <start> – <end> (<timezone>)
- **Tester(s):** <names>
- **Report version:** 1.0 (<date>)   • **Classification:** <Confidential>
- **Method:** <black-box / grey-box; which skills/phases ran; egress used>

## 1. Summary

<One paragraph. Overall risk posture, count by severity, the 1–3 things that
matter most, and whether anything is being actively exploited. No tool names in
this paragraph — the reader is a decision maker.>

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 0 |
| Informational | 0 |

**Top risks**
1. **<F-01 title>** — <one line: what it means for the business, not the CWE.>
2. **<F-02 title>** — <…>
3. **<F-03 title>** — <…>

## 2. Findings

<!-- Repeat this block per finding, ordered Critical → High → Medium → Low → Info.
     One finding = one root cause. Two tools reporting the same issue = one finding. -->

### F-01 — <Short title: what is broken, where>

- **Severity:** Critical • **CVSS:** 9.8 `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`
- **Affected:** `<host or repo>` — `<endpoint, file, parameter, version>`
- **CWE:** CWE-<id> (<name>) • **CVE:** <id or "none">
- **Status:** Confirmed (reproduced) / Best-effort (requires precondition X)

**What it is.** <2–4 sentences, precise. Name the missing check, the trust
boundary crossed, or the logic error.>

**Proof.**
```http
POST /api/v1/<path> HTTP/1.1
Host: <host>
<the exact request that demonstrates it — headers that matter, body>
```
```http
HTTP/1.1 200 OK
<the exact response, or the extracted data proving impact; redact real PII as
<redacted> and keep the shape>
```
<For code findings: file:line and the 5–10 line snippet that matters.>

**Impact.** <Who can do this, from where, and what do they get. Quantify when
possible: "all 12,400 customer records", "any authenticated user", "one
tenant's data". If impact depends on a precondition, state the precondition.>

**Steps to reproduce.**
1. <…>
2. <…>
3. <Observed: …>

**Remediation.**
<The fix, specific to the stack. Name the framework control, not "sanitize
input". If there is a temporary mitigation, separate it from the real fix.>
- Fix: <…>
- Verify: <the test the developer runs to confirm it is fixed — this should be
  a request/response or a unit test, not "review the code">

**Effort.** <hours/days> • **Priority:** <P0 fix now / P1 this sprint / P2 next>

---

### F-02 — <…>

<!-- … same block … -->

## 3. Condensed table (Medium / Low / Informational)

| ID | Severity | Finding | Location | Fix (one line) |
|---|---|---|---|---|
| F-06 | Medium | <…> | `<endpoint>` | <…> |
| F-07 | Low | <…> | `<host>` | <…> |
| F-08 | Info | <…> | `<host>` | <…> |

## 4. Chains

<Only if findings combine into something worse than their parts. Show the
sequence explicitly: what an attacker does first, what it buys, what it unlocks.
If nothing chains, delete this section rather than writing "none".>

| Chain | Findings | Result |
|---|---|---|
| C-01 | F-03 → F-04 → F-07 | Unauthenticated read of every tenant's API keys |

## 5. What was tested

| Area | Skill / method | Result |
|---|---|---|
| External surface | subdomain enum + port scan (nmap) | 47 hosts, 112 services |
| Web apps | `web-app-pentest`, `api-security-test` | 2 Critical, 1 High |
| Auth/session | `auth-session-security` | no finding |
| Business logic | `business-logic-fuzzing` | 1 High |
| Cloud config | `iac-cloud-posture` | not applicable |

**Explicitly out of scope:** <…>. **Not tested (and why):** <e.g. "destructive
tests were excluded", "no credentials for the admin console were provided">.

A clean result for one area is not a clean result overall — say so here, in
those words, so the reader calibrates correctly.

## 6. Artifacts

| File | Contents | SHA-256 |
|---|---|---|
| `evidence/F-01.req.txt` | exact request/response | `<hash>` |
| `evidence/F-03-poc.py` | working PoC | `<hash>` |

<Evidence is archived with hashes so "we cannot reproduce it" can be settled.
Never ship credentials in evidence — reference the credential store instead.>

## 7. Appendix — severity rubric used

| Severity | Meaning in this report |
|---|---|
| Critical | Direct, unauthenticated path to RCE, full data access, or auth bypass for all users |
| High | Privileged-only code execution, bulk sensitive-data read, or auth bypass with a precondition |
| Medium | Data or function access outside your own permission set, single-record exposure, requires a user action |
| Low | Hardening gap with a plausible exploit path, information leak that materially aids another step |
| Info | Best practice deviation, no direct exploit |
````

## Fill-in rules

- **Severity reflects exploitability + blast radius + reachability**, not the
  scanner's label. A "Critical" CVE on an unreachable host is Info.
- **Every claimed finding carries its own proof.** If there is no request /
  response / file:line, it is a `Best-effort` finding or it does not ship.
- **Redact secrets and third-party PII** in evidence; keep one intact copy in
  the encrypted evidence archive.
- **Never write a finding you cannot re-run.** "May be vulnerable" is not a
  finding; it is a note for the next round.
- **Delete advisory language.** No "we recommend reviewing security practices"
  — say which control, in which file, does what.
