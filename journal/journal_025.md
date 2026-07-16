# Journal Entry 025: The List That Works Until It Doesn't

**Date**: July 16, 2026
**Focus**: A cursor pagination convention for remote functions, and the dispatch gap hiding under it
**Status**: Shipped

## The Path of Least Resistance

Issue #53 is one of those problems that isn't a bug so much as a shape the
framework quietly encourages. Nothing about the remote-function layer says
anything about pagination, neither example app demonstrates it, and so the
obvious way to write any listing function is what the blog's own
`get_posts()` did: `SELECT everything ORDER BY published_at DESC`, return
the lot. It works at ten rows, it works at a hundred, and there is no
signal anywhere in dev that it stops working later. The fix isn't to police
it. It's to make the paginated version copyable enough that it becomes the
new path of least resistance.

## Page[T] Doesn't Make It Out Alive

The shape I wanted was the obvious one: a generic `Page[T]` TypedDict in
the framework, `def list_posts(...) -> Page[PostSummary]`, one type to rule
them all. So before writing anything I ran `Page[PostSummary]` through the
codegen typemap to see what the client would get.

`unknown`. Not an error, not a warning, just `unknown` and no interface
emitted. A subscripted generic TypedDict isn't a `type`, so it falls past
the TypedDict branch, past the dataclass branch, past everything, and lands
in the fallback. Meanwhile a plain per-module TypedDict comes out as a real
interface with every field intact. I could have taught the typemap about
`Generic` aliases, but that's a rabbit hole with pydantic, forward refs and
the stdlib fallback all wanting opinions, and the convention needs to be
copyable today. So the convention is the boring version, and the docs say
so out loud: declare `PostsPage` yourself, three lines, done. The framework
ships the helpers, not the type.

## The Blocker Nobody Ordered

The signature I wanted was `list_posts(cursor: str | None = None,
limit: int = 20)`. Call it with no arguments, get page one. Except when I
traced what actually happens when the browser calls `list_posts()`: the
generated client always sends every positional slot, so an omitted argument
goes over the wire as devalue `undefined`, and the server's `validate_args`
demanded an exact argument count and then choked on `UNDEFINED` where an
`int` should be. A 422 for calling a function exactly as its signature
invites you to.

There was a second, sneakier version of the same problem: for
`cursor: str | None`, the union validator tried the `None` branch, and the
`None` branch passes anything through untouched. So `UNDEFINED` didn't fail
validation there, it *arrived in the function* as a sentinel object that
`cursor is None` doesn't catch. Nothing in the codebase had ever hit either
case, because no existing remote function had a default parameter. The
convention was going to be the first, so the convention had to come with
the fix: an omitted or `undefined` argument now means "use the parameter's
default," which is exactly what `undefined` means at the JS call site, and
an `undefined` for a parameter with no default is a clean validation error.

## Opaque Cursors, One Extra Row

The helpers themselves (`fymo/remote/pagination.py`) stayed small on
purpose. `encode_cursor(*values)` is base64url of a JSON list of the
last-seen sort-key values. `decode_cursor` reverses it and treats anything
malformed as a 400 `bad_cursor` through the existing `RemoteError`
machinery: bad base64, non-JSON, an empty list, the wrong arity, and also
nested JSON values, because a cursor that decodes to `[["a"],{}]` isn't a
sort key and shouldn't get anywhere near a query binding where it would
blow up as a driver error and surface as a 500. Cursors are client input.
They will be tampered with, and tampering should cost the tamperer a 400,
not me a stack trace.

The query side is the fetch-one-extra idiom: ask for `limit + 1` rows, and
if the extra one comes back you know there's a next page without a second
`COUNT(*)` round trip. `paginate(rows, limit, key=...)` drops the extra
row and encodes the last kept row's keys as `next_cursor`, or `None` when
the extra row didn't show. The helpers never see a database. The SQL stays
in app code where it belongs.

One thing the blog example forced me to get right: `published_at` alone is
not a cursor. Two posts can share a timestamp, and a cursor that can't
name an exact position either skips a row or repeats one. So the example
sorts by `(published_at, slug)` and uses SQLite's row-value comparison,
`WHERE (published_at, slug) < (?, ?)`, and the integration test seeds two
posts on the same date specifically to catch anyone (me, later) simplifying
the tiebreak away.

## Wiring It Into the Blog

`get_posts()` stays, untouched, because tests depend on it and because the
contrast is sort of the point. Next to it now lives `list_posts(cursor,
limit) -> PostsPage`, and the home page uses it end to end: the controller
SSRs the first page and threads `list_posts` itself into the template as a
prop, the same marker-object trick the comments form already used, and the
template grows a "More posts" button that feeds `next_cursor` back in until
it comes back null and the button disappears.

The e2e check was the satisfying part. Real build, real wsgiref socket,
curl for the transport: three pages of posts including the tied-date pair
in the right order, seven slugs total with no duplicates and no gaps, the
final page answering `next_cursor: null`, an argless call landing on the
defaults, and a garbage cursor bouncing off as a 400 `bad_cursor` instead
of a 500. Then ten more rows straight into the SQLite file and a re-curl of
`/` to watch the button actually render once the table outgrew the first
page.

## What I'd Watch For

The defaults fix is the piece with reach beyond pagination. Every remote
function can now have optional trailing parameters and be called the way
its Python signature reads, which is strictly better, but it also means a
hand-written client that sends *fewer* args than the signature has is no
longer an automatic error when the missing ones have defaults. That's the
correct trade, it mirrors how Python itself treats the call, but it's a
behavior change in the dispatch path and it's the first thing I'd look at
if some future optional-parameter function misbehaves.

The other loose end is `Page[T]`. The typemap could learn generics someday,
and if it does, the convention can graduate without breaking anyone,
because a generic that emits the same `{ items, next_cursor }` interface is
wire-identical to the hand-rolled TypedDict. Until then the docs promise
nothing the codegen can't deliver.
