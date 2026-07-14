# Journal Entry 011: The Jobs Worker Was a Black Box

**Date**: July 14, 2026
**Focus**: A `logging:` section in `fymo.yml`, one root-logger handler shared by the app and the jobs worker, fail-fast config validation, per-job lifecycle logs
**Status**: Shipped

## The Question That Started It

I was poking at the jobs worker, trying to confirm a queued job had actually run, and the honest answer was: I couldn't tell. `fymo jobs-worker` printed nothing. Not "job picked up," not "job done," nothing on failure either — a job could raise, get retried, raise again, and the terminal would stay silent through all of it. I asked myself the obvious question: does the jobs worker even log?

Turned out the answer was worse than "logging is off." The worker process had never called anything that configures logging in the first place. Procrastinate, the queue library underneath it, does its own `logging.getLogger("procrastinate")` calls, but with no handler installed anywhere in the process, Python's default behavior swallows everything below WARNING. So even the library's own visibility into what it was doing was mostly invisible. The web process had request logging from early on, and I'd apparently just never pointed the same attention at the worker, because it wasn't the thing serving requests. It was the thing sitting in a terminal tab I never watched closely enough.

## One Config Section, Two Processes

The fix needed to cover both the web process and `fymo jobs-worker` from the same source, or I'd end up with two different logging stories to maintain. So `fymo.yml` gets one `logging:` section — destination (terminal or file), level, format — and both processes resolve it through the same function, `resolve_logging_config()`.

The default is terminal in both dev and production. That took a second to settle on, because my first instinct was "surely production wants a file, that's what production log files are for." But the moment I actually thought about how these processes get deployed — Docker, systemd, gunicorn workers under a process supervisor — the answer flips. All of those already capture stdout/stderr and hand it to whatever log driver or journal is doing the real work downstream. Defaulting to file logging in production would mean fymo trying to be its own log shipper, badly, when the platform underneath it is already doing that job properly. Twelve-factor got this right a decade ago: logs are an event stream, not a file fymo should own the lifecycle of. File output stays available, but it's opt-in — you ask for it explicitly when you actually want a local file, not because fymo assumed you did.

## Why the Root Logger, Not Fymo's Own

The more interesting decision was where to attach the handler. fymo already had its own `logging.getLogger("fymo")` for access logs. The easy path would've been to keep configuring just that logger and leave everything else alone. But that's exactly the setup that left me staring at a silent worker terminal — Procrastinate's logger isn't `fymo.anything`, it's its own namespace, and no handler on `fymo` was ever going to catch it.

So `configure()` installs one handler on the root logger instead. Everything below it — fymo's own logs, whatever the app calls `logging.getLogger(__name__)` for, Procrastinate's internals — funnels through the same destination and the same formatter. That's the only way "the worker even logs" becomes true in a way that includes the library doing the actual queue work, not just the thin wrapper fymo puts around it. One handler, one place log lines can end up, instead of a namespace-by-namespace game of whack-a-mole every time some dependency turns out to have its own logger nobody configured.

## Fail Fast, Not Fail Quiet

Config validation for the `logging:` section is deliberately strict: bad `destination`, missing `file` when destination is `file`, an unrecognized `level` or `format` — all of it raises `ValueError` at startup naming the bad key and the allowed values. I could have made every one of those fall back to a sane default and kept running. I didn't want to, because that's precisely the failure mode that bit me with the worker. A misconfigured logging section that silently degrades to "logs go somewhere, or nowhere, who knows" is how you end up debugging an incident three weeks from now and discovering the log line you needed was never written, or was written to a path nobody's tailing. Better to refuse to boot with a clear message than to boot quietly wrong.

## Quiet When Healthy

Per-job logging turned out to need three levels, not one: started, succeeded, failed. Succeeded is INFO, failed is ERROR with the traceback attached, and started is DEBUG. That last one was a small but deliberate choice — at INFO, which is what most people run in production, a worker chewing through a normal queue produces one line per completed job, not two. You see confirmation that work happened and how long it took, and you don't see a "started" line for every job that was always going to succeed a moment later. Turn on DEBUG when something looks stuck and you get the finer-grained view; leave it at INFO and a healthy worker reads as calm, not chatty. Job arguments never get logged at any level — duration and outcome tell you what you need without also being the thing that leaks whatever a job happened to be called with.

## What Didn't Make the Cut

Rotation was the first thing I dropped. It's tempting to reach for `RotatingFileHandler` and call it done, but logrotate and every container log driver already solve this, and solve it better — they handle compression, retention windows, and external rotation signals in ways a hand-rolled Python rotation policy inside fymo never would. Building a worse version of something the platform already owns isn't a feature.

Dual destinations — terminal and file at once — I also cut, at least for now. It's a real thing people ask for eventually (send to file for durability, still mirror to terminal for local dev-server watching), but stdlib's handler system already supports attaching more than one handler if you need it; fymo just doesn't need to pre-build that combination when a single destination is what nearly everyone reaches for first.

And I didn't build a provider abstraction around any of this — no `LoggingProvider` interface, no pluggable backend registry. It's Python's own `logging` module underneath, one handler, one formatter, configured once. If someone needs a second sink — Sentry, some hosted log service — the doc now says exactly where to attach it: `server.py`, after fymo's own `configure()` call, using the standard library's own `addHandler`. That's not a gap fymo needs to paper over with an abstraction; it's the interface stdlib logging already gives you for free.

Full suite's still green after all of it — 604 passing now, up from 573 at the start of this, zero failures. The worker terminal isn't silent anymore either, which was really the whole point.

---

*End of Journal Entry 011*
