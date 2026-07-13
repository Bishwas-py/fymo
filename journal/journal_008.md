# Journal Entry 008: Production Readiness - The Unglamorous Sprint

**Date**: July 12, 2026
**Focus**: gunicorn, health checks, structured logging, security hardening, finishing auth
**Status**: ✅ Shipped

## The Gap Between "Works" and "Deployable"

Fymo ran great on a dev server and had real features. It also had no
production story whatsoever: no real WSGI server integration, no health
endpoint, print-style logging, a pile of known security findings, and auth
missing its boring-but-essential flows. This was the sprint where none of
the work is fun to demo and all of it matters.

Three phases, one branch, each independently committable.

## Phase A: Deployable Runtime

- `fymo serve --prod` boots gunicorn (already a dependency, now actually
  used) with worker lifecycle hooks. The Node sidecar is per-worker: each
  gunicorn worker owns its own sidecar process, spawned on worker boot and
  reaped on exit. Getting the sidecar lifecycle right was most of the work
  here.
- `/healthz` liveness probe, dispatched before rate limiting so a k8s probe
  polling aggressively never sees a 429 and mistakes a healthy instance for
  a dead one. It also skips access logging, or health checks would drown
  real traffic in the log stream.
- `fymo/core/logging.py`: human-readable lines in dev, one JSON object per
  line in prod, plus access-log middleware with request timing. Configured
  idempotently so repeated app construction in tests doesn't stack
  duplicate handlers (learned that one the hard way).
- A Dockerfile and a deployment doc, with a smoke test that actually builds
  and boots the image.

## Phase B: Security Findings

The accumulated list, closed: error-page output escaping (XSS via
traceback), CSP and HSTS defaults in prod, `Secure` cookie flag resolution
behind a proxy (`trust_proxy` + `X-Forwarded-Proto`), request body caps,
token-bucket rate limiting keyed by client IP and path rule, and login
enumeration equalization (same timing and same response whether the email
exists or not).

Also `@remote` explicit opt-in: by default any function in `app/remote/`
is exposed, which is convenient but wide. `remote.explicit_optin: true`
flips it so only decorated functions ship. The build-time discovery and the
runtime router have to agree on this flag or you get functions in the
manifest that 404 at dispatch; the tests pin both sides.

## Phase C: Auth, Finished

- SSR-time sessions: the renderer now opens a request scope, so
  `current_user()` works during server rendering and the logged-in Nav
  renders correctly on first paint. This killed the logged-out flash noted
  in entry 006.
- Email verification and password reset: token columns on the user store,
  remote functions for the flows, and an `EmailSender` seam whose default
  implementation just logs the verification link (no SMTP dependency for
  dev; real senders plug in via the same dotted-path config as everything
  else).

## Secrets

One rule, enforced early: secrets come from env, never YAML, never
committed files. The HMAC secret for signing cookies resolves from
`FYMO_SECRET`, falls back to a generated per-project `.fymo/secret.key` in
dev, and refuses to boot in prod with neither. Loud failure beats forgeable
cookies.

## Lesson

Every item in this sprint was small. The value was in the sweep: sitting
down with the full list and refusing to call the framework production-ready
until the list was empty, instead of fixing whichever item bit most
recently.

---

*End of Journal Entry 008*
