# syntax=docker/dockerfile:1
#
# Production image for a Fymo application.
#
# Fymo needs BOTH Node and Python at two different times:
#
#   - Build time: `fymo build` compiles Svelte components via esbuild, which
#     shells out to Node. This needs Node 20+ and the project's npm
#     dependencies installed. Output goes to dist/ (hashed client bundles +
#     dist/sidecar.mjs). dist/sidecar.mjs is NOT esbuild-bundled — it is
#     copied as plain ESM and contains a bare `import { render } from
#     'svelte/server'`, which Node resolves from node_modules at runtime.
#     That means node_modules (with svelte and devalue installed) MUST be
#     present in the runtime image, not just the build stage.
#
#   - Run time: `fymo serve --prod --workers N` runs the app under gunicorn.
#     Each gunicorn worker process owns its own Node child ("the sidecar",
#     `node dist/sidecar.mjs`) that it talks to over a pipe for SSR. That
#     means the RUNTIME image needs `node` on PATH AND node_modules
#     (svelte, devalue) — a python-only runtime image boots fine but every
#     request fails at render time because there is no sidecar to render
#     with, and a runtime image missing node_modules boots and passes
#     liveness but crashes the sidecar on the first SSR render with
#     ERR_MODULE_NOT_FOUND, leaving /healthz permanently 503.
#
# This Dockerfile therefore uses Node as the base for both stages: stage 1
# builds the frontend and installs Python on top to run the `fymo` CLI;
# stage 2 is a slim runtime that keeps Node + node_modules (for the sidecar)
# and adds only the Python runtime + installed packages needed to serve.

# ---------------------------------------------------------------------------
# Stage 1: build — Node (for esbuild) + Python (for the `fymo build` CLI)
# ---------------------------------------------------------------------------
FROM node:20-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first (better layer caching): install fymo + gunicorn + any
# app-specific requirements into a venv.
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

# Node deps next: esbuild, svelte, and whatever the app declares. `npm ci`
# requires package-lock.json to be committed — do that for reproducible,
# cache-friendly builds (this is what `fymo new` scaffolds expect once you
# run `npm install` once locally).
COPY package.json package-lock.json ./
RUN npm ci

# Now the app source, and build. `fymo build` shells out to `node` to run
# esbuild — that's why this stage is FROM node, not FROM python.
COPY . .
RUN fymo build

# ---------------------------------------------------------------------------
# Stage 2: runtime — still Node-based (sidecar needs `node`), slim Python on top
# ---------------------------------------------------------------------------
FROM node:20-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin fymo

WORKDIR /app

# Bring over the venv (fymo, gunicorn, app deps) built in stage 1 — no pip
# install needed here, keeping the runtime image lean.
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Bring over the built app (server.py, fymo.yml, app/ routes+components,
# dist/ including dist/sidecar.mjs, AND node_modules). node_modules must be
# kept: dist/sidecar.mjs is not esbuild-bundled — it does a bare
# `import { render } from 'svelte/server'` that Node resolves from
# node_modules at runtime. Deleting node_modules here would let the
# container boot and pass liveness, then crash the sidecar with
# ERR_MODULE_NOT_FOUND on the first SSR render, leaving /healthz stuck at
# 503. Do NOT `npm prune --production` either — svelte/devalue may be
# declared as devDependencies in some project package.json layouts, so a
# production prune can strip exactly what the sidecar needs.
COPY --from=build /app ./

RUN chown -R fymo:fymo /app
USER fymo

# --- Required runtime configuration ---------------------------------------
# FYMO_SECRET: a >=16 char random string used to sign auth cookies/session
# state. Production refuses to boot without it. NEVER bake a real secret
# into the image — inject it at `docker run` / orchestrator level, e.g.:
#   docker run -e FYMO_SECRET="$(cat /run/secrets/fymo_secret)" ...
# See docs/deployment.md for provisioning via env vars / secret managers.
# Deliberately not declared with `ENV` here — there is no default that
# would be safe to ship in an image; it must come from the runtime
# environment (docker run -e / compose env_file / orchestrator secret).
#
# FYMO_DEV must stay unset (or "0") in production — leaving it unset here is
# intentional; do not set FYMO_DEV=1 in a production image.

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# --workers is deliberately modest by default: each gunicorn worker spawns
# its own Node sidecar process, so worker count multiplies memory usage
# (Python worker + Node child, each). Tune via `docker run ... fymo serve
# --prod --workers N` or by overriding CMD; see docs/deployment.md for
# sizing guidance.
CMD ["fymo", "serve", "--host", "0.0.0.0", "--port", "8000", "--prod", "--workers", "4"]
