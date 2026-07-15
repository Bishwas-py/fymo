# Journal Entry 013: Three Commands, One Working By Accident

**Date**: July 15, 2026
**Focus**: `fymo dev` never actually enabled dev mode; `fymo serve` was a worse `fymo dev` wearing a different name; `fymo serve --prod` trusted the shell more than it should have
**Status**: Shipped

## Tracing It End to End

I went in expecting to fix one thing and found three commands tangled together, none of them behaving the way their name promised. I started by asking a simple question: if I run `fymo dev` in a fresh project, does the app actually end up in dev mode? I traced `run_dev()` all the way down and the answer was no. It called `create_app(project_root)` with no `dev` argument, which falls back to reading `FYMO_DEV` from the environment — and `run_dev()` never set that variable. So `fymo dev`, the command whose entire job is "run this in dev mode," silently produced a production-configured app unless you'd separately exported `FYMO_DEV=1` yourself. Error pages without tracebacks, secure-only cookies, full rate limiting, on the one command that exists specifically to turn all of that off.

Then I looked at `fymo serve`. With `FYMO_DEV=1` exported by hand, it did resolve dev=True correctly, but it booted through a completely different path — importing the project's `server.py`, pulling out the already-constructed `app` object, and handing it straight to the plain wsgiref server. No watcher, no esbuild rebuild-on-save, no sidecar hot-reload. And it had a `--reload` flag that did nothing but print a warning telling you it did nothing. Without `FYMO_DEV` exported, plain `fymo serve` ran with full production security defaults on that same single-process server — not a real dev environment, and not something you'd actually want serving traffic either. Three ways to start a server, and depending which one you picked and what was in your shell, you got some inconsistent blend of dev ergonomics and production security that matched neither label.

The last piece was worse in a quieter way: `fymo serve --prod` built its WSGI app the same way, by importing `server.py`, which meant its `dev` flag also came from whatever `FYMO_DEV` happened to be set to in the shell at that moment. A stray `export FYMO_DEV=1` left over from an earlier dev session, forgotten in a long-lived terminal, could silently boot a production deploy in dev mode. That's not a hypothetical — it's exactly the kind of thing that survives in a shell profile or a leftover `.env` someone sourced once and never unset.

## The One Real Decision

Fixing the first and third problems was direct: make `fymo dev` set `FYMO_DEV=1` and pass `dev=True` explicitly, first thing, instead of relying on an env var it never set. Make `--prod` force `FYMO_DEV=0` before it ever imports `server.py`, so nothing inherited from the shell can leak in.

The open question was what to do with bare `fymo serve`. It didn't earn its own identity — depending on flags and env state it was either a broken dev server or an underpowered production one. I could kill it outright, or turn it into a straight alias for `fymo dev`. I went with alias. The reason wasn't sentiment about backward compatibility for its own sake — it's that `fymo new`'s own printed next-steps, the scaffolded `package.json`'s `dev` script, the README, and both example apps all told a new user to type `fymo serve` first. Deleting the command would have broken onboarding for anyone following docs written before this fix landed, for zero benefit — aliasing gets the exact same outcome (a broken command becomes a working one) without that cost. `fymo serve` with no `--prod` now does exactly what `fymo dev` does, byte for byte, because it just calls into it. `--prod` is still the one real production path. I updated the scaffolding and docs to point at `fymo dev` as the canonical name going forward, since the whole complaint here was commands not matching their names, but I didn't make the alias an error just to enforce that on people who type `serve` out of habit.

One more small thing fell out of that decision: the generated `server.py` had an `if __name__ == "__main__":` block that called a `run_dev_server()` helper directly, completely bypassing the CLI and the dev pipeline — a fourth way to start a server, and the one most likely to confuse someone who ran `python server.py` expecting the watcher to be running. Since `fymo dev` and the `fymo serve` alias no longer import `server.py` at all, that block was dead weight pointing at the wrong thing. Dropped it. `server.py` is now what it always should have been: a plain WSGI entrypoint for gunicorn, uwsgi, or `fymo serve --prod`, nothing more.

## Proving It, Not Just Testing It

Unit tests with mocked collaborators are fine for pinning down the wiring, and I wrote those first — a failing assertion that `run_dev()` sets `FYMO_DEV` and passes `dev=True`, one that `--prod` forces the env var false even with a stray truthy value already set, one that bare `serve` actually delegates to `run_dev`. All of them failed against the old code for the reason I expected, then passed once I made the change.

But mocks can lie to you about timing, and a review pass caught exactly that in my first version of the `--prod` test — it only checked the final state of the environment variable after `run_server()` returned, which would still pass even if the fix accidentally set the variable *after* importing `server.py` instead of before. I rewrote it to use a real `server.py` that calls `create_app()` the way an actual scaffolded project does, and assert on the constructed app's `.dev` attribute directly, so the test fails if the ordering is ever wrong again, not just if the end state happens to look right.

For the real proof, I used something already built into the app: production refuses to boot without a signing secret, but dev mode will auto-generate one at `.fymo/secret.key` the first time it starts. That's a real, unmocked signal for exactly the bug I was fixing. I copied one of the example apps into a scratch directory with no `FYMO_SECRET` set and no existing secret file, ran the actual `fymo dev` command against it, and watched `.fymo/secret.key` get written and the server come up and answer a real HTTP request — proof dev mode was genuinely on, not just that a test double said so. Then I ran the mirror image: a fresh copy, `FYMO_DEV=1` exported in the shell exactly like someone would forget to unset, and `fymo serve --prod` against it. It refused to start, demanding `FYMO_SECRET`, exactly as production should when it hasn't been told otherwise — proof the stray env var couldn't leak through anymore. Same trick a third time confirmed bare `fymo serve` takes the dev path too. Three real server processes, not three mocked function calls.

Full suite: 676 passing, 106 skipped, zero failed.

---

*End of Journal Entry 013*
