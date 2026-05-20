# Operator guide — monitoring `ADMIN_TOTP_BYPASS`

> Audit N-8. Centralised guide for SRE / on-call on what to alert on,
> where the bypass is read, and how to triage a “bypass enabled in
> production” incident. This complements the inline comments in
> `backend/app/auth_2fa.py` and the test-side notes in
> `tests/conftest.py` and `tests/helpers.py`.

## TL;DR

- `ADMIN_TOTP_BYPASS` is a **test-only** env var. When it is set to a
  non-empty value, the admin-side TOTP gate (`/admin/*/decide`,
  `/admin/users/*/role`, taxonomy mutations, withdrawals…) accepts
  `X-Totp-Code: <value>` instead of a real TOTP code.
- It **must not be set** in production or staging. A bypass enabled in
  production downgrades the second factor on every admin endpoint to a
  shared secret — see the *Threat model* section below.
- The backend logs a single structured warning at startup if the var
  is non-empty (event name `auth_2fa.bypass.enabled`); your log
  pipeline should fire on this and your dashboards should expose it.

## Where the bypass is wired

| Layer | Location | Notes |
|---|---|---|
| Backend read | `backend/app/auth_2fa.py::_totp_bypass` | Re-reads `os.environ` per call so an operator-side `unset` takes effect on the next request without a process restart. |
| Startup warning | `backend/app/auth_2fa.py` module top | Single `logger.warning` with `extra={"event": "auth_2fa.bypass.enabled"}` when the value is non-empty. **Do not** broaden this to log the value itself. |
| Test-only consumer | `tests/conftest.py`, `tests/helpers.py::admin_totp_bypass_value` | Generates a fresh random value per pytest invocation and reads the same env var. |
| Skill reference | `.agents/skills/testing-garant-tma/SKILL.md` | Documents the local `docker-compose.override.yml` pattern for e2e testing. |

## Threat model

If `ADMIN_TOTP_BYPASS=<value>` leaks into production:

1. The admin TOTP gate accepts `X-Totp-Code: <value>` from any
   authenticated user that is also `is_admin`/`is_arbiter`. The
   per-user TOTP secret (`users.totp_secret`) is bypassed.
2. The compromise blast-radius is bounded by the admin allowlist —
   non-admin users still receive 403 — but **every** admin-level
   sensitive action becomes single-factor (the Telegram session).
3. The value is not user-secret per se: leakage via process listings,
   `/proc/$pid/environ`, container-orchestrator env dumps, container
   image inspection, etc. all expose it.

## Monitoring requirements

### Required — startup warning alert (P1)

Fire on any log line with structured field `event = auth_2fa.bypass.enabled`
emitted by a `production` or `staging` deployment. This is the
authoritative signal: the warning is emitted once per process start
when the variable is non-empty.

Example Loki query (LogQL):

```
{app="garant-backend", environment=~"production|staging"}
  | json
  | event = "auth_2fa.bypass.enabled"
```

Recommended alert: page on **any** match. Auto-resolves on the next
deploy if the var is unset.

### Required — periodic env audit (P2)

Schedule a job (Argo CD post-sync hook, Helm test, or a `kubectl exec
... -- env` cron) that inspects the running pod's environment and
fails loud if `ADMIN_TOTP_BYPASS` is set. The startup warning above is
emitted only on process boot, so a long-running pod where the var was
set after boot (e.g. through a Kubernetes `EnvFromSource` change with
a rolling update that didn't reach the admin replicas) would
otherwise be invisible.

The check should redact the value — log only the presence/length, not
the contents.

### Optional — request-side telemetry (P3)

The TOTP gate does not currently emit a structured event when a
request is admitted via the bypass code path. If you need
per-request visibility (e.g. to confirm "no admin actions used the
bypass in the last 24 h"), add a `logger.info(... extra={"event":
"auth_2fa.bypass.used"})` next to the comparison in
`backend/app/auth_2fa.py::_consume_totp`. Do this only in concert
with a deliberate decision — it's deliberately quiet today because
the bypass should be inert in production.

## Incident playbook

If the startup-warning alert fires in production / staging:

1. **Stop traffic to the affected service** by either:
   - rolling back the deployment with the env var change, or
   - scaling the deployment to zero while preserving stateful
     dependencies (DB, Redis).
2. **Rotate every admin account's TOTP secret** in `users.totp_secret`
   (`UPDATE users SET totp_secret = NULL, totp_last_counter = 0
   WHERE is_admin = TRUE OR is_arbiter = TRUE;` followed by an
   out-of-band 2FA re-enrolment with each admin). This invalidates
   any cached TOTP codes an attacker may have observed via the
   bypass.
3. **Audit the admin-action log** (`admin_audit_log` table) for the
   window between the var first being set and the rollback. Pay
   special attention to:
   - `users.role` changes (privilege escalation).
   - Withdrawal `/decide` actions on `approve`.
   - `wallets/*/adjust` rows.
   - Taxonomy changes (categories / currencies) — used to inject
     malicious payment instructions.
4. **Confirm the var is not stored in any committed config** (`grep`
   the chart values, the deployment manifest, the secret manifest).
5. Post a post-mortem.

## Local-dev / CI usage

Setting the var locally or in CI is fine and expected. The startup
warning will fire there too — that's the dev/CI confirmation that
the bypass code path is wired up. Filter on `environment` (`test` /
`development`) in your alerting rules so dev noise doesn't page.

Reference setup for local Docker: see
`.agents/skills/testing-garant-tma/SKILL.md` — *Injecting test-only
env vars*.
