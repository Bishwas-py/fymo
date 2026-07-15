# Journal Entry 014: The Provider Nobody Could Reach

**Date**: July 15, 2026
**Focus**: A runtime accessor for the configured StorageProvider
**Status**: Shipped

## The Complaint

A video-recording job needed to know where to write its finished file. Not
a hypothetical, a real one: something driving a headless browser, recording
a session, and needing to land the result wherever `storage:` in fymo.yml
says it should live. It reached for the obvious thing first, and the
obvious thing turned out not to exist.

`StorageProvider` gets built exactly once in this codebase, inside
`FymoApp.__init__`, and only when `media:` is configured. There was no
accessor for anything else. So the job did what jobs do when the framework
doesn't give them a door: it found a window. It imported
`fymo.build.prepare.read_yaml_section`, a function whose own docstring says
"used only to thread config into build-time discovery, not the runtime
config loader" — and reimplemented the prefix-matching dir-resolution loop
that `build_media_routes` already does internally, by hand, badly,
duplicated.

That's the whole bug report, really. Not a crash, not a wrong answer, just
a job that had to go around the framework because the framework hadn't
built the door yet.

## What the Issue Actually Asked For

The ticket sketched `get_storage_provider(project_root)`, off `fymo.storage`,
"built the same way FymoApp builds its own internally." Reasonable enough
sketch. But I'd just spent an entry pulling `fymo.jobs` and `fymo.broadcast`
apart and found they'd already solved this exact problem, twice, the same
way: a process-wide singleton, installed once by an `init_X(project_root,
config)` call at startup, read anywhere after with a no-arg `get_X()`. `fymo
jobs-worker` — a separate OS process from the web server — already calls
both `init_job_provider()` and `init_broadcasts()` at its own startup for
exactly this reason: it needs the same providers the web process has,
without carrying a socket or a shared-memory segment between them.

A `get_storage_provider(project_root)` that rebuilds from `fymo.yml` on
every call would work today. It would also mean re-parsing YAML and
reconstructing the provider on every single call site, which is fine for
`LocalStorageProvider` and a real cost the moment #17 lands and a provider
is holding an S3 client. And it would be the third storage-shaped thing in
this codebase that doesn't match how the other two work. I went with the
singleton instead — same shape as jobs and broadcasts, `set_/get_/init_/
reset_storage_provider()` in `fymo/storage/__init__.py` — and wrote the
deviation from the issue's own sketch down explicitly rather than quietly
picking one, since it's the kind of call someone reading the PR later
should be able to see was made on purpose.

## The One Place It Can't Mirror the Pattern

`get_job_provider()` and `get_broadcast_provider()` both fall back to a
working default if nothing initialized them — an unconfigured
`ThreadedJobProvider`, a default `PostgresBroadcastProvider`. That's the
right call for those two. It is very much not the right call for storage.
`build_storage_provider` has refused a default since the day it was
written, on purpose: silently writing to local disk is the kind of thing
that works fine on a laptop and quietly loses every uploaded file the
moment the app runs behind a load balancer with more than one instance.
Copying the "fall back to a default" half of the jobs/broadcasts pattern
here would have undone that guarantee for the sake of API symmetry, which
is a bad trade. `get_storage_provider()` raises a clear error instead,
naming the fix, if nothing has called `init_storage_provider()` yet. Same
shape as the other two singletons everywhere except the one line where
being the same shape would have been a regression.

## Decoupling Storage From Media

The bigger structural change was inside `FymoApp.__init__` itself. Storage
only ever got constructed inside the `if media_config:` branch, which made
sense back when the only consumer of a `StorageProvider` was the media-route
handler. It stopped making sense the moment a job wanted one too, since
plenty of real apps will want write access to storage without wanting a
single declarative `media:` route. So `FymoApp` now builds storage whenever
`storage:` is configured, full stop, and hands that one instance to both
`self.storage_provider` and to `build_media_routes` if `media:` also
happens to be configured. Before this, a hypothetical app with both `media:`
and `storage:` set would already build one provider for the media routes;
after this, that's still exactly one provider, just reachable from
everywhere instead of sealed inside the media-routes branch. Checked for
that specifically — `get_storage_provider() is app.storage_provider` is one
of the assertions — because the alternative bug (two providers, one for
media routes and a second one built separately for the singleton) would
have been invisible until someone hit a real backend where constructing a
client twice actually costs something.

`fymo jobs-worker` got the matching change: one more `init_storage_provider`
call, sitting right next to the `init_broadcasts` call it already makes,
gated the same way — only if `storage:` is actually configured, no default
invented for the worker process either.

## Writing Down a Pattern Before It's Needed

The issue flagged something worth catching before #17 (S3/R2 providers)
lands: `write(key, data)` takes a complete `bytes` payload. There's no
append, no stream. A live Playwright recording can't call `write()` until
it's finished, because there's nothing to write yet. The pattern is record
to a scratch path on local disk, then read the whole thing back and call
`write()` once — and that's not a workaround for local storage's
limitations, it's the actual shape the API will keep once storage is S3 or
R2 too, since neither of those offers "keep appending to this key" either.
Put that directly in `fymo/storage/__init__.py`'s module docstring, next to
`get_storage_provider` itself, on the theory that documentation nobody
reads on the way to using the thing might as well not exist.

## Proving It

TDD start to finish — wrote the singleton tests first and watched them fail
on a plain `ImportError` before `get_storage_provider` existed, then the
`FymoApp` integration tests, which I stashed the server.py change to
confirm actually failed for the reason I expected (an `AttributeError` on
`app.storage_provider`, then a `RuntimeError` from the un-primed singleton)
before unstashing it. Full suite: 776 passed, 10 skipped, all ten skips
needing a real Postgres instance the test environment doesn't have, nothing
to do with this change. And because a green test suite isn't the same as a
working feature, I built a real todo-app fixture, called `create_app` with
only a `storage:` section and no `media:` at all, and wrote a file through
`get_storage_provider()` from outside `FymoApp` entirely — the exact shape
of thing the original job would have wanted to do, minus the hand-rolled
YAML parsing.

---

*End of Journal Entry 013*
