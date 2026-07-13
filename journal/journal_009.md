# Journal Entry 009: Job Providers + Broadcasts - The Scalability Arc

**Date**: July 12-13, 2026
**Focus**: Durable Postgres-backed job queue, then real-time push to the browser
**Status**: ✅ Shipped (fymo 0.4.0 through 0.6.0)

## The Bug Report That Started It

While recording a flow in the monitoring app (an AI agent driving a
headless browser for 30-90 seconds), reloading the page just... hung.
Everything hung. The dev server was a plain single-threaded wsgiref server,
so one long request starved the entire process. My own reaction at the
time: "you told me we were prod ready, we are not even dev ready." Fair.

The in-process JobRunner (entry 007) could unblock the request, but the job
still lived and died with the web process. A deploy or a crash silently
killed any in-flight recording, and there was no way to scale "how many
agent sessions can run" separately from "how many requests can be served."
This needed the real thing: a durable queue and a separate worker process.

## Picking the Queue

Requirements: survives restarts, scales independently, and adds no
infrastructure beyond the Postgres the app already uses. No Redis, no
RabbitMQ, no Celery operational overhead.

[Procrastinate](https://procrastinate.readthedocs.io/) fit exactly:
Postgres-native, mature, actively maintained, uses LISTEN/NOTIFY internally
for near-instant job pickup instead of polling. I verified the deal-breaker
questions against the real library before committing: deferring works from
fully synchronous code (`SyncPsycopgConnector`), and a task can be a plain
`def` (each sync task runs in its own thread inside the worker). Our task
bodies use Playwright's sync API and the sync OpenAI SDK, so that mattered.

## The Seam

Same pattern as auth providers, deliberately:

```yaml
# fymo.yml
jobs:
  provider: procrastinate   # or "threaded" (default), or a class: path
```

`JobProvider` Protocol with `register_tasks()` / `submit()` /
`run_worker()`. Tasks are plain functions in `app/jobs/*.py`, discovered
like `app/remote/*.py`. A remote function calls
`get_job_provider().submit("do_record_work", ...)` and returns immediately.
`fymo jobs-worker` runs the worker loop as its own OS process with its own
restart policy and scaling.

The app change was surgical. `record()` went from doing the whole agent
session inline to: create the run row, submit, return the row. Measured
before and after on the real app: the request dropped from 30-90 seconds of
blocking to 70 milliseconds, with other pages serving in ~2ms while the
worker ground away.

## Then the Browser Needed to Know

With jobs running elsewhere, the UI was polling `get_run()` every 2 seconds
to notice completion. Polling works but it's the wrong shape; the server
knows the exact moment a run finishes. So, broadcasts: push, designed to
feel like remote functions.

```python
# app/broadcasts/runs.py
def run_status(run_id: str) -> RunStatusEvent:
    """Args = what you subscribe with. Return type = what you receive.
    The body runs at subscribe time as an authorization guard."""
    ...
```

```python
# from the job, in the worker process
publish("run_status", run_id=run_id, data={"status": "passed", ...})
```

```ts
// browser, generated typed client
import { subscribe } from '$broadcast/runs';
const unsub = subscribe.run_status({ run_id }, (data) => { ... });
```

Transport is SSE on the browser side and Postgres LISTEN/NOTIFY underneath,
which is what makes the cross-process story work: the worker NOTIFYs, any
web worker holding a matching LISTEN pushes the frame. Same primitive
Procrastinate already uses, zero new infrastructure. Channel keys hash
module + channel + subscribe args, so two users watching different runs
never see each other's events. Payloads cap at NOTIFY's 8KB with a loud
error saying "send ids, not blobs."

The guard-body idea is my favorite part of the design. The channel function
looked like it would be a dead declaration (signature for codegen, no
body). Instead the body runs on every new subscription, inside the same
request scope remote functions get, so `current_user()` works and a raise
or `return False` becomes a 403 before any LISTEN happens. The declaration
earns its keep.

Delivery is fire-and-forget by design. EventSource reconnects on drops, but
missed events are gone; the database stays the source of truth and the UI
keeps a slow safety-net poll (15s) for the gaps. Broadcasts mean "something
changed, look now," not "this is the data."

## What Nearly Bit Me

- **The dev server again.** An open SSE connection parks a thread, and
  wsgiref is single-threaded, so one subscribed tab would have frozen dev
  completely. The threaded dev server (ThreadingMixIn, daemon threads) had
  to ship first. Wrote the regression test, then verified it against the
  old server: /fast queued 1.8 seconds behind /slow there, under 5ms after.
- **`importlib.reload` keeps stale attributes.** Discovery used reload for
  cached modules, and reload reuses the module dict, so functions from a
  previously imported version leaked into rediscovery. The jobs tests never
  asserted the *absence* of stale tasks, so it shipped unseen; writing the
  broadcasts discovery tests caught it in both. Evict and fresh-import now.
- **Queue competition.** A leftover worker process on the shared dev
  database kept stealing the test suite's jobs. Not a code bug, but a good
  reminder that a shared queue is shared.
- **Missing-extra UX.** Configuring `provider: procrastinate` without
  `pip install 'fymo[procrastinate]'` dumped a raw ModuleNotFoundError. CI
  (which doesn't install extras) caught it. Now it's a clear error with the
  install command, and the DATABASE_URL check runs before the import so the
  more common misconfiguration reports first.

## Why Not Redis

Asked myself seriously, since "job queue + pub/sub" usually reads as Redis.
But Postgres already does both jobs here (queue tables, LISTEN/NOTIFY), and
a second infrastructure piece means a second failure mode plus the classic
queue-says-X-database-says-Y consistency bugs. Rails 8 dropped Redis for
database-backed defaults for the same reason. The provider seams mean a
Redis transport can slot in later with one config line if some app ever has
tens of thousands of concurrent subscribers. One great default, never a
dead end.

## The Verification That Made It Real

End to end, on the real app, as a browser would experience it:

```
: subscribed
data: {"status": "passed", "error": null, "run_video": "page@fc08...webm"}
```

Subscribe over SSE, trigger a record, the worker (separate OS process)
picks the job off Postgres, runs the agent, persists script + video, and
the frame arrives pushed, about 8 seconds later. Page loads stayed at ~5ms
the whole time. That's the moment the whole arc paid off.

---

*End of Journal Entry 009*
