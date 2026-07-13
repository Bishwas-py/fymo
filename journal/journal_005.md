# Journal Entry 005: Stealing SvelteKit's Wire Format (Legally)

**Date**: April 28, 2026
**Focus**: devalue serialization, hashed endpoints, 200-always envelopes, CSRF
**Status**: ✅ Shipped

## Why Touch a Working Wire Format

Remote functions shipped with a serviceable v1 wire:
`POST /__remote/<module>/<fn>`, plain JSON args, `{"ok": true, "data"}` or
`{"ok": false, "error"}`. Fine. But since the whole feature is
SvelteKit-inspired, I sat down and read SvelteKit's actual remote-function
source (`runtime/server/remote.js`, the client runtime, `shared.js`) to see
what they do differently. Three things stood out, and all three were better
than what I had.

## 1. devalue Instead of JSON

SvelteKit serializes with [devalue](https://github.com/Rich-Harris/devalue),
a tagged JSON dialect. Plain JSON silently mangles things: `datetime`
becomes a string and never comes back, `Map`/`Set`/`undefined` are simply
unrepresentable, repeated references get duplicated.

With devalue on both directions, `Date`, `Map`, `Set`, `BigInt`, `RegExp`,
`undefined`, repeated references, and (on the Python side) `Decimal`,
`UUID`, `Enum`, and `bytes` all round-trip with full fidelity. Args are
devalue-stringified and base64url-encoded onto the wire.

I wrote a devalue implementation in Python for this. That was the bulk of
the work, and the test matrix (every type, both directions, nested, with
reference cycles) is one of the more thorough suites in the repo.

## 2. Hashed URLs

SvelteKit endpoints look like `/remote/<HASH>/<fn_name>` where the hash is a
build-time identifier of the source file. Nobody can enumerate your
functions by guessing module names. So fymo now hashes each
`app/remote/*.py` (`sha256(file_content)[:12]`), bakes the hash into the
manifest, the generated client stubs, and the SSR-emitted markers:

```json
"remote_modules": {
  "posts": { "hash": "4f3a9c1b8e2d", "fns": ["get_posts", "create_comment"] }
}
```

A function is unreachable unless its hash appeared in a rendered page.

## 3. Always 200, Type in the Body

Responses are always HTTP 200 with a discriminated envelope:
`type: "result" | "error" | "redirect"`. Status codes ride inside the body.
Fetch-layer plumbing stops caring about HTTP status entirely, and redirects
become a first-class response instead of an exception. CSRF is an
`Origin === Host` check at the router, before anything else runs.

## The Discipline Part

The tempting move was restructuring everything while I was in there. I
didn't. Function definitions, the `$remote` resolver, prop threading, and
codegen all stayed bit-for-bit identical. Only the wire boundary changed.
App code written against v1 needed zero edits.

Punted to v2: function kinds (`@query`/`@form`/`@command`), query batching,
single-flight mutations, the public `transport` hook for custom encoders
(the internals exist, the API surface doesn't yet).

## Lesson

Reading the reference implementation's source beats guessing at its design
from docs. All three changes came from specifics I'd never have gotten from
the SvelteKit documentation alone.

---

*End of Journal Entry 005*
