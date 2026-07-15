# Production deployment

This covers running a Fymo app in production: the process model, the
reverse-proxy setup in front of it, secret provisioning, worker sizing, the
health check, and log shipping.

> **The `Dockerfile` at the fymo repo root is a per-project template, not a
> file you build from this repo.** Copy it (and `.dockerignore`) into your
> Fymo *project* directory — the one containing `server.py`, `fymo.yml`,
> `app/`, `requirements.txt`, and `package.json` (the layout `fymo new`
> scaffolds) — and run `docker build` from there. `docker build` uses your
> current directory as the build context, so running it against the
> framework repo root instead of your project directory will not produce a
> working image.

## Process model

`fymo serve --prod --workers N` runs the app under gunicorn. Gunicorn owns
the worker processes; each worker is a full Python process that also spawns
its own Node child process (`node dist/sidecar.mjs`) to perform SSR. That
sidecar is not shared across workers — it's created fresh after each fork
(see `fymo/server/gunicorn.py`) — so a running production instance looks
like:

```
gunicorn arbiter
├── worker 1 (python) ──spawns──> node dist/sidecar.mjs (SSR child)
├── worker 2 (python) ──spawns──> node dist/sidecar.mjs (SSR child)
└── worker N (python) ──spawns──> node dist/sidecar.mjs (SSR child)
```

This is why the runtime container image needs **both** Python and Node —
see `Dockerfile` at the repo root for a reference multi-stage build. A
Python-only runtime image will boot and pass basic smoke checks, but every
page render will fail once traffic hits it, because there's no Node
sidecar to render with.

## Reverse proxy (nginx / Caddy) and TLS

Gunicorn (via the `sync` worker class fymo configures) should sit behind a
reverse proxy that terminates TLS. Don't terminate TLS in gunicorn itself.

- **Caddy** terminates TLS (including automatic cert issuance/renewal) and
  reverse-proxies to the app:

  ```
  example.com {
      reverse_proxy 127.0.0.1:8000
  }
  ```

  Caddy sets `X-Forwarded-Proto` and `X-Forwarded-For` automatically.

- **nginx** needs this set explicitly:

  ```nginx
  server {
      listen 443 ssl;
      server_name example.com;

      location / {
          proxy_pass http://127.0.0.1:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
  }
  ```

### `trust_proxy`

Fymo's rate limiter identifies clients by IP (`fymo/core/middleware.py`).
By default it reads `REMOTE_ADDR`, which — behind a reverse proxy — is the
proxy's own IP, not the client's. Set `trust_proxy: true` in `fymo.yml`
**only** once you have a reverse proxy in front that you trust to set (and
overwrite, not append to) `X-Forwarded-For`:

```yaml
limits:
  rate_limit:
    enabled: true
    requests_per_minute: 60
    trust_proxy: true
```

If `trust_proxy` is enabled without a trusted proxy in front, a client can
spoof `X-Forwarded-For` and bypass per-IP rate limiting entirely. Leave it
`false` (the default) if the app is ever exposed directly.

The same `trust_proxy` flag also gates whether HSTS (below) trusts
`X-Forwarded-Proto` — one trust boundary, not two to keep in sync.

## Security headers: default CSP + HSTS

In production (`dev=False`), fymo adds two headers on top of the always-on
`X-Content-Type-Options` / `X-Frame-Options` / `Referrer-Policy` /
`Permissions-Policy` set, unless overridden (see below):

**`Content-Security-Policy-Report-Only`** — a `default-src 'self'`
baseline (`fymo/core/middleware.py`, `DEFAULT_CSP_REPORT_ONLY`):

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data: https:; font-src 'self' data:; connect-src 'self';
object-src 'none'; base-uri 'self'; frame-ancestors 'none'
```

It ships in **report-only** mode, not enforcing. Reasons:

- fymo's SSR page itself only needs `script-src 'self'` (the hydration
  entry point is a same-origin `<script type="module" src="/dist/...">`;
  the JSON prop/doc islands use `type="application/json"`, which browsers
  never execute as script — CSP doesn't apply to them regardless of
  policy).
- But `fymo.yml`'s `head.script.analyticsID` / `hotjar` / `custom` options
  (see `fymo/core/template_renderer.py`) inject **inline** `<script>`
  blocks and third-party script hosts (Google Tag Manager, Hotjar) when
  configured. An *enforcing* `script-src 'self'` would silently break
  those the moment an app turns one on — the exact "broke it out of the
  box" outcome this default is meant to avoid.

Report-only ships the header (so `Content-Security-Policy-Report-Only` is
visible from day one and violations show up in the browser devtools
console) without breaking anything.

**To move to an enforcing policy:**

1. Set your own CSP explicitly via `security.headers.extra` in
   `fymo.yml` — this always wins over the default, whether you use
   `Content-Security-Policy` (enforcing) or
   `Content-Security-Policy-Report-Only`:

   ```yaml
   security:
     headers:
       enabled: true
       extra:
         - ["Content-Security-Policy", "default-src 'self'; script-src 'self' 'nonce-<per-request-nonce>'"]
   ```

2. If you use `analyticsID` / `hotjar` / `custom` inline scripts, either:
   - add their required hosts to `script-src` (e.g.
     `https://www.googletagmanager.com https://static.hotjar.com`), or
   - switch to nonces: generate a per-request nonce, add
     `'nonce-<value>'` to `script-src`, and add `nonce="<value>"` to each
     inline `<script>` tag. fymo doesn't generate nonces for you today —
     `security.headers.extra` is a static list evaluated once at startup,
     so a true per-request nonce needs a small wrapper around
     `wrap_start_response`/your own middleware until first-class nonce
     support lands.
3. Test in report-only first (watch the browser console / a configured
   `report-uri`) before switching to enforcing, since a too-strict policy
   fails closed (blocks the resource) rather than open.

**`Strict-Transport-Security`** (`max-age=31536000; includeSubDomains`) is
added when the **resolved** request scheme is https — via
`resolve_scheme(environ, trust_proxy)` in `fymo/core/middleware.py`, the
same function that governs the session cookie's `Secure` flag. Behind a
TLS-terminating reverse proxy the app sees plain http on the wire, so this
honors `X-Forwarded-Proto` **only when `trust_proxy: true`** (see above) —
the same anti-spoof gate as the rate limiter's `X-Forwarded-For` handling.
Without `trust_proxy`, only a direct https connection triggers HSTS; a
client spoofing `X-Forwarded-Proto: https` over plain http cannot force it
on.

Both defaults are skipped entirely in dev (`dev=True` / `FYMO_DEV=1`): no
CSP noise on localhost, and HSTS is never forced (it would break plain
http on localhost, and browsers cache it well past the dev session).

## `FYMO_SECRET`

Fymo signs auth cookies and session state with an HMAC key. In production
(`dev=False` / `FYMO_DEV` unset or `0`), the app **refuses to boot** unless
`FYMO_SECRET` is set to a string of at least 16 characters — this is a
deliberate loud failure over silently running with a forgeable cookie.

Generate one with:

```sh
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Provisioning rules:

- **Never commit it.** It must not appear in `Dockerfile`, `fymo.yml`,
  version control, or CI logs.
- Inject it as an environment variable at deploy time, e.g.:
  - `docker run -e FYMO_SECRET="$FYMO_SECRET" ...`
  - a platform's secret manager (AWS Secrets Manager / SSM Parameter Store,
    GCP Secret Manager, HashiCorp Vault, Kubernetes `Secret` mounted as an
    env var) resolved into the container's environment at startup.
- Use the **same** secret across all workers/replicas of one deployment —
  it's what lets a session signed by one process validate on another.
  Rotating it invalidates all existing sessions/cookies.
- Keep `FYMO_DEV` unset (or `0`) in production. Setting it enables
  dev-only behavior (verbose tracebacks in 500s, cookies without the
  `Secure` flag) that must never run in production.

## Environment variables in `fymo.yml`

`fymo.yml` can reference environment variables directly, so a
deployment-specific value (an auth issuer URL, an API base URL) doesn't
force a custom Python class just to read `os.environ`:

```yaml
auth:
  providers:
    - type: oidc
      id: auth0
      authorize_endpoint: ${AUTH0_AUTHORIZE_ENDPOINT}
      token_endpoint: ${AUTH0_TOKEN_ENDPOINT}
      userinfo_endpoint: ${AUTH0_USERINFO_ENDPOINT}
      client_id_env: AUTH0_CLIENT_ID
      client_secret_env: AUTH0_CLIENT_SECRET
```

- `${VAR}` resolves to the environment variable's value. If it's unset,
  config loading fails immediately with a `ConfigurationError` naming the
  variable, rather than silently loading a config with the literal string
  `${VAR}` in it.
- `${VAR:-default}` falls back to `default` (including an empty default,
  `${VAR:-}`) when `VAR` is unset. The default itself may reference
  another placeholder, e.g. `${A:-${B}}`, resolved the same way and only
  evaluated when `A` is actually unset.
- The resolved value is always spliced back in as a quoted YAML string, so
  a value can never be interpreted as YAML structure (an extra key, a new
  list item) no matter what characters it contains, including a literal
  newline. An env var populated from a less-trusted source than the yml
  file itself (a build pipeline, a secrets manager with looser access)
  still can't restructure the config, only supply a string value.
- Interpolation runs on the raw YAML text before parsing, so it works
  anywhere in the file, not just inside `auth:`, and that includes inside
  `#` comments: a `${VAR}` written in a comment is still substituted and
  validated (an unset required var there still raises), since the
  substitution pass has no notion of YAML comments.

### `.env` for local development

In dev mode (`dev=True` / `FYMO_DEV=1`), Fymo loads a `.env` file from the
project root into the process environment before `fymo.yml` is parsed, so
`${VAR}` placeholders and any code reading `os.environ` can see it:

```
CLERK_ISSUER=https://example.clerk.accounts.dev
DATABASE_URL=postgres://localhost/myapp_dev
```

- One `KEY=value` per line. Blank lines and lines starting with `#` are
  ignored. A value may be wrapped in matching single or double quotes,
  which are stripped.
- A real environment variable already set (exported in the shell, set by
  the process manager, etc.) always wins — `.env` never overwrites it. Use
  this to override a single value for a one-off run without editing the
  file.
- **Never read in production.** `.env` is only loaded when `dev=True`; a
  production process (`dev=False`, the default when `FYMO_DEV` is unset)
  never touches it, even if a `.env` file exists on disk (e.g. committed by
  accident).
- Add `.env` to `.gitignore` in your project — Fymo doesn't do this for
  you, since project scaffolding and `.gitignore` are separate concerns.

### Conditional auth providers: `required: auto`

A provider entry can carry `required: auto` to make its inclusion depend
on whether it's actually configured, instead of the app crashing on a
missing required constructor argument or silently registering a
half-broken provider:

```yaml
auth:
  providers:
    - type: clerk
      required: auto
```

With `required: auto` set, the registry calls the provider class's
`is_configured()` classmethod **before** constructing it. If that returns
`False`, the provider is skipped entirely: no error, no instance, it
contributes nothing to the app. This lets a provider stay dormant in local
dev (no Clerk/Auth0/etc. env vars set) and activate once real values land
in the environment, with no separate conditional wiring in app code.
Any value other than the literal string `"auto"` for `required` (a typo
like `Auto`, or anything else) raises a `ProviderConfigError` naming the
bad value, rather than being silently ignored or crashing the provider's
constructor with an unrelated `TypeError`.

`ClerkProvider` implements this fully out of the box: `is_configured()`
checks for `CLERK_ISSUER`, falling back to decoding the Frontend API domain
out of `PUBLIC_CLERK_PUBLISHABLE_KEY` (Clerk's own `pk_test_`/`pk_live_` key
shape), and `from_config()` derives `jwks_url` as
`{issuer}/.well-known/jwks.json` when it isn't given explicitly. Neither
env var needs a custom wrapper class or an explicit `issuer:`/`jwks_url:`
in `fymo.yml` -- the config block above is the entire setup.

`is_configured()` defaults to `True` on `BaseProvider`, so every existing
provider is unaffected: only an entry that both sets `required: auto` and
points at a provider overriding the hook gets the conditional behavior.

## Worker sizing

Each gunicorn worker costs one Python process **plus** one Node sidecar
process. Sizing purely on CPU core count (the usual `2 * cores + 1` rule of
thumb) will overcommit memory here — budget for:

```
total memory ≈ workers × (python_worker_rss + node_sidecar_rss)
```

Measure `python_worker_rss` and `node_sidecar_rss` for your app under
representative load (component tree size and SSR payload size both affect
the Node side) before picking a worker count, and leave headroom rather
than sizing to the limit. Start conservative (e.g. `--workers 2`–`4` on a
single host) and scale workers with observed memory, not just CPU.

`--workers` is set via the CLI/CMD, so it can be tuned per-environment
without rebuilding the image:

```sh
fymo serve --host 0.0.0.0 --port 8000 --prod --workers 4
```

## Health check

`GET /healthz` is a liveness probe that bypasses auth, rate limiting, and
the body-size cap. It pings the current worker's Node sidecar:

- `200 {"status": "ok"}` — sidecar responded, worker is healthy.
- `503 {"status": "degraded"}` — the sidecar is unavailable (crashed,
  hung, not yet started).

Point your load balancer / orchestrator health check (Docker
`HEALTHCHECK`, Kubernetes liveness/readiness probe, ALB target group
health check, etc.) at this path. Because gunicorn workers each own an
independent sidecar, `/healthz` reflects the health of whichever worker
served that particular request — a load balancer polling repeatedly across
workers will catch a single degraded worker within a few checks.

`/healthz` is intentionally excluded from access logging (see
`fymo/core/server.py`) so frequent polling doesn't drown out real request
logs.

## Log shipping

In production (`FYMO_DEV` unset/`0`), fymo emits one JSON object per line
per request to stdout/stderr — no text formatting, no multi-line
tracebacks mixed into the stream (see `fymo/core/logging.py`):

```json
{"method": "GET", "path": "/todos", "status": 200, "duration_ms": 4.21}
```

Only method, path, status, and duration are logged — never cookie values,
request bodies, or auth headers.

Don't write logs to a file inside the container. Let the process log to
stdout/stderr and let the container runtime's log driver (Docker
`json-file`/`local`, Kubernetes' pod log stream, etc.) or a sidecar log
shipper (Vector, Fluent Bit, Filebeat) pick lines up and forward them to
your log backend (CloudWatch, Loki, Elasticsearch, Datadog, ...). Because
each line is already a single JSON object, most shippers can parse it
without a custom grok/regex rule.

## Logging

fymo logs to the terminal by default — in production (`FYMO_DEV` unset)
as one JSON object per line on stderr, which Docker, systemd, gunicorn,
and any log collector pick up natively. Configure via `fymo.yml`:

```yaml
logging:
  destination: file      # terminal (default) | file
  file: log/fymo.log     # required when destination: file
  level: info            # debug | info | warning | error
  format: json           # text | json (default: text in dev, json in prod)
```

The same section drives both the web process and `fymo jobs-worker`,
which also emits one line per background job (started/succeeded/failed,
with duration). Job arguments, cookies, request bodies, and auth headers
are never logged. (fymo's own log lines never include them, and the
`procrastinate` library's argument-echoing lines are suppressed in the
worker: its logger is capped to WARNING by default, and its
permanent-failure line — which would pass at ERROR — is filtered out;
fymo's own `job failed` line carries name/status/duration and the
traceback instead. Explicitly `setLevel(logging.INFO)` on the
`procrastinate` logger only if you accept that its lines will include
job arguments.)

fymo owns a single handler on Python's root logger, so your app's own
`logging.getLogger(...)` output and library logs share the destination
and format. Attach additional handlers in `server.py` if you need a
second sink (e.g. Sentry) — this only takes effect under `fymo serve
--prod`, which imports `server.py`. `fymo dev` and bare `fymo serve`
build the app directly and never import it, so module-level code in
`server.py` doesn't run locally.

File output is append-only with no built-in rotation — use logrotate or
your container platform's log driver.

## Media routes (byte-range file serving)

Apps that need to serve binary files with `Range` support (video/audio
seeking and scrubbing, in particular) don't need to hand-write a raw WSGI
route for it. Declare them in `fymo.yml` instead:

```yaml
media:
  - prefix: /media/videos/
    dir: data/videos
    extensions: [webm]
```

`prefix` is matched against the request path the same way fymo's own
`/dist/` and `/assets/` routes are (a path prefix, not a template). `dir`
is resolved relative to the project root. `extensions` is the allow-list
for the filename after the prefix; anything else, and any filename
containing `..` or starting with `/`, gets a 400.

fymo owns the rest: single-range `Range: bytes=start-end` requests get a
206 with `Content-Range`, full-file requests get a 200 with `Content-Length`,
missing files get a 404, and `Content-Type` is resolved from the filename
via the standard library's `mimetypes` module. `media:` can list multiple
entries with different prefixes/dirs/extensions, and the section is
entirely optional, apps without one register no extra routes at all.

See `fymo/core/media.py` for the implementation, and `fymo/core/http.py`
for the lower-level raw-WSGI extension point (`app/routes.py`) this sits
alongside, for the rarer case of a route that isn't just "serve a file
from a directory" (webhooks, non-file responses, etc.).
