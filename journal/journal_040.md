# Journal Entry 040: One Alias Was Wearing a Namespace

**Date**: July 18, 2026
**Focus**: $fymo/auth becomes $auth
**Status**: Shipped

## The Odd One Out

The client-side virtual modules had settled into a convention without
anyone declaring it: bare names. `$route`, `$remote/posts`,
`$broadcast/chat`. Then the identity rework shipped the auth store as
`$fymo/auth`, and suddenly one module out of four carried a vendor
prefix. There is a respectable argument for namespacing framework-owned
modules, SvelteKit does it with `$app/`, but that argument needed to be
made for all of them or none of them, and `$route` had already voted
none. A convention with one exception is not a convention, it is a
trivia question.

So: `$auth`. One word, same shape as its siblings, and the store lands
flat at `dist/client/_auth.js` instead of inside a `_fymo/` directory
that existed to hold exactly one module.

## Teaching Through the Error

The interesting part of a rename is never the new name, it is everyone
holding the old one. There is no deprecation window here, pre-1.0 this
project breaks clean, but breaking clean and breaking mute are different
things. If the old specifier just stopped resolving, esbuild would shrug
out a could-not-resolve and the developer would go spelunking. Instead
the build plugin keeps a resolver for the retired `$fymo/` prefix whose
entire job is to fail with the sentence you need: renamed to `$auth`,
update the import. Nothing resolves through it. It is not a shim, it is
a tombstone with directions.

I wrote that test first and watched it fail because the old import still
built fine, which is exactly the wrong kind of success. Flipping the
whole test suite's expectations before touching the code turned the
rename into a checklist: five files went red, then green one by one,
and the last grep for the old prefix came back with nothing but the
error message itself, which is the one place the old name is supposed to
live from now on.

---

*End of Journal Entry 040*
