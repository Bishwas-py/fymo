# Journal Entry 023: Finishing a Sentence Someone Else Started

**Date**: July 16, 2026
**Focus**: A server-side redirect primitive — the client half had been shipping since before I ever raised it
**Status**: Shipped

## Dead Code With a Pulse

The report was unusual in a specific way: it wasn't "this is broken," it was
"half of this already works and nobody noticed." A grep across the whole
package confirmed it. `entry_generator.py`, in the generated `__rpc` helper
every route bundle carries, had this sitting in it, twice:

```js
if (env.type === 'redirect') { window.location.href = env.location; return; }
```

`codegen.py`'s typed `$remote` client runtime had the identical branch. Two
independent code paths, both written to expect a JSON envelope shaped
`{"type": "redirect", "location": "..."}`, and not one line anywhere on the
Python side that ever produced it. The client had been carrying a feature
that literally could not fire. Somebody wrote this expecting the other half
to follow shortly after, and it never did.

Meanwhile the only place fymo actually writes a `Location` header is the
OAuth providers' raw HTTP routes, which don't go through `getContext()` or a
remote function at all — they're their own thing, bypassing the whole
envelope mechanism. So a page controller that decides "you shouldn't be
here" has exactly two moves: render anyway, or raise an error page. It can
never say "go to `/login`."

## Finding the Seam Before Building Next to It

The instinct with a new exception type is to add a new `try/except` wherever
it needs to be caught. I didn't want to do that here, because fymo already
has one of these — `AuthRequired` — and I wanted to know exactly how it
travels before deciding whether a redirect should travel the same way or
needs its own path.

Tracing it: `AuthRequired` is a `RemoteError` subclass, and `RemoteError` is
already the seam. The remote router catches it around every function
dispatch and turns it into `{"type": "error", "status": ..., "error": ...}`.
`template_renderer.py` catches it too, around the full-page SSR render, so a
controller's `getContext()` calling `get_post(slug)` and hitting a missing
row gets a real 404 page instead of a flattened 500 — that fix predates this
one. Two files, one exception hierarchy, one convention: subclass
`RemoteError`, and both the RPC path and the SSR path already know what to
do with you.

Except one of them didn't, quite. `soft_nav.py` — the endpoint that serves
soft navigations, `GET /_fymo/data/<path>` — wraps the same controller
invocation in a bare `except Exception`. No `RemoteError` branch at all. A
`NotFound` raised from `getContext()` during a soft nav was landing as a
flattened `controller_failed` 500, silently losing its real status and
code, the exact bug the SSR path had already been fixed for. Nobody had
carried the fix over because nobody had gone looking at both files side by
side for this specific reason before. I only found it because the task
asked me to.

So the actual plan wasn't "add a redirect path." It was: make a `Redirect`
that's just another `RemoteError` subclass, fix the gap in `soft_nav.py`
while I was already standing in exactly the right spot to see it, and let
all three sites — router, renderer, soft-nav — special-case the one
subclass that isn't really an error inside the `except RemoteError` block
they already have, instead of writing a fourth thing.

```python
class Redirect(RemoteError):
    status = 303
    code = "redirect"

    def __init__(self, location: str, status: int = 303):
        super().__init__(f"redirect to {location}", status=status, code="redirect")
        self.location = location
```

`303 See Other` as the default, matching the conventional POST-redirect-GET
status. Everything else about it stayed a normal `RemoteError` — same
constructor shape, same status/code fields — because the whole point was
that nothing downstream needs to know it's special except the three call
sites that pick the wire form.

## Two Wire Forms, One Header the Return Type Didn't Have

The remote-function path was mechanical once the seam was clear: catch
`Redirect` before the generic `RemoteError` branch, emit
`{"type": "redirect", "location": e.location, "status": e.status}` instead
of the error envelope. Same for `soft_nav.py`, same envelope shape, since
it's consumed by the same kind of client code either way.

The SSR path needed something the code didn't have a place to put:
`render_template()` returned `Tuple[str, str]` — html, status — and had
nowhere to hang a `Location` header. Every caller, every test, unpacked
exactly two values. I could have smuggled the header through some
side-channel, but that's the kind of thing that looks clever for a week and
confusing for a year. Changed the return shape to a 3-tuple instead —
`(html, status, extra_headers)` — and pushed the change through the actual
call chain: `TemplateRenderer.render_template` → `FymoApp.render_svelte_template`
→ the WSGI handler that builds the response headers list. Thirteen existing
call sites across four test files needed the third element added to their
unpacking. All mechanical, all the same one-line change, and the compiler —
well, Python doesn't have one, but `ValueError: not enough values to unpack`
found every one of them for me the first time I ran the suite.

For a `Redirect`, the SSR renderer now returns an empty body and
`[("Location", e.location)]` — browsers don't render a 30x body, they just
follow the header. Status line stays consistent with how every other
`RemoteError` subclass in this file already formats one, `e.code.upper()`,
so a redirect prints `303 REDIRECT` instead of the textbook `303 SEE OTHER`.
That reads slightly unusual next to curl output, but HTTP clients decide
navigation from the numeric code, not the reason phrase, and I'd rather
match the file's existing convention than invent a second one for one
status.

## The Client Half Had a Gap of Its Own

While I was in `entry_generator.py` confirming exactly what shape the
`__rpc` branch expected, I noticed the *other* client function in the same
file — `softNav()`, the one that actually drives a soft navigation by
fetching `/_fymo/data/<path>` — only checked for `env.type === 'error'`. No
redirect branch. If `soft_nav.py`'s newly-fixed `getContext()` path ever
raised a `Redirect` during a soft nav instead of a full page load, the
client would fall through, try to `parse(env.result)` on `undefined`, and
throw somewhere nobody was catching it. Since I'd just made the server side
support exactly that case, leaving the client half broken would have meant
shipping a mechanism that only worked from a fresh page load and silently
broke the second you clicked into the app first. Added the same one-line
branch there too, in both templates (the plain route and the layout-shell
route each generate their own copy of this function).

## Proving the Dead Branch Actually Runs

The acceptance bar here was specific on purpose: not "the server returns the
right JSON," but "the client branch that's been sitting there unreachable
actually executes." That meant driving a real click through a real compiled
bundle, not asserting on a devalue string.

fymo already has the tool for this — `hydration_check.mjs`, a jsdom
harness that boots the actual esbuild output with a real `hydrate()` call,
built for exactly this kind of "does the browser actually do the thing"
proof. It has an `afterBoot` hook for driving interaction after a clean
boot. I added a tiny demo page to the blog example — one remote function,
`go_to_login()`, that unconditionally raises `Redirect("/login")`, wired to
a button — and wrote a test that boots the real page, clicks the real
button, and waits.

First run threw immediately: `Failed to parse URL from /_fymo/remote/.../go_to_login`.
jsdom doesn't implement `fetch` at all, so the bundle's `fetch(url)` call
was resolving to Node's own global fetch — and Node's fetch has no notion
of a page origin the way a browser does, so it can't resolve a relative
URL. Fixed by wrapping `fetch` for the duration of the click to prefix
relative paths with the real server's origin, which is exactly what a
browser does for you automatically and the only reason it needed doing by
hand here.

Second problem was worse, because it wasn't a crash, it was a silent no-op.
`window.location.href = '/login'` executed without error and the location
never changed. jsdom simply doesn't implement navigation — it logs "Not
implemented: navigation to another Document" and leaves `location` alone.
I tried to intercept it three different ways before finding one that
worked: redefining `window.location` directly (jsdom marks it
non-configurable, throws), redefining `.href` on the `Location` prototype
(also non-configurable, and it turns out `href` isn't even on the
prototype — it's an own property on each instance), and finally swapping
out the `window` *binding itself* for a fresh object that inherits
everything from the real jsdom window except `location`, which points at a
plain recordable stub instead:

```js
globalThis.window = Object.create(originalWindow, {
  location: { value: { href: null }, configurable: true },
});
```

That works because nothing else in this exact click's code path touches
`window` — the redirect branch is the only thing that does, right at the
end, after the fetch and the JSON parse are already done. Click, wait, read
the stub's `href` back: `/login`, exactly what the server's `Redirect`
carried. To make sure the test wasn't a tautology, I reverted the router's
redirect handling and re-ran it — it failed for the right reason, an
uncaught `Error: redirect to /login` thrown by the generic error branch the
old code fell into, exactly the failure mode the whole feature exists to
prevent.

## What I Left Alone

The issue asked, explicitly, whether a redirect target should be validated
— same-origin clamping, the kind of thing `oauth.py`'s `_safe_next` already
does for its own `next` parameter. I didn't add it. `_safe_next` exists
because that value comes from a query string an attacker can set; `Redirect`'s
location comes from the app's own source code, the same trust boundary
every other `RemoteError` subclass already lives inside. Fymo doesn't
decide when to redirect or validate where to — that's the app's call, same
as it already is for every other exception in this file. If an app ever
builds a redirect target out of user input, clamping it is that app's job,
the same way it already is for anyone hand-rolling a `Location` header
today.

## The Count

830 passing, 92 skipped — the skips are pre-existing, an unrelated example
app's `node_modules` and a Postgres integration test that needs a real
database, neither touched by this change. One dead branch, written months
ago for a feature that didn't exist yet, finally executed for the first
time — watched it happen, in a real jsdom-hydrated page, clicking a real
button, on a run where I'd deliberately broken the server first to
watch it fail before watching it pass.

---

*End of Journal Entry 023*
