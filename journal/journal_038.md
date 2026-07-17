# Journal Entry 038: The Framework Stops Owning Your Users

**Date**: July 17, 2026
**Focus**: Deleting `User`, `UserStore`, and every shipped auth provider; identity becomes a string your code produces
**Status**: Shipped

## The Test Auth Kept Failing

I have a three-part test for anything the framework ships as a subsystem:
you can opt out of it completely, it owns only its own tables, and it
never leaks into your domain types. `jobs:` passes all three. You skip
the config block and Procrastinate never existed; its tables are its
business; nothing in your schema points at it.

Auth failed all three, and the failures compounded. Nearly every app has
users, so everyone inherited `fymo_users` whether they wanted it or not.
A Clerk-only app that stores no passwords still booted a SQLite user
store, because the store was wired unconditionally the moment auth was
enabled. And because `fymo_users` existed and was the natural identity
table, app schemas grew foreign keys into a framework-owned, runtime
bootstrapped table, which is how you end up arguing with schema diff
tools about tables you never wrote.

The `UserStore` Protocol was the tell. Twelve methods, four of them
password-reset plumbing. Anyone bringing their own storage had to stub
flows they never used, because the framework had decided what a user was.

## Mechanism, Not Model

The replacement is one dataclass with one field. `Identity(uid: str)`.
An app registers resolvers with `@identify` in `app/auth/`, the first
resolver returning an Identity wins, `current_uid()` reads the result.
That is the entire runtime contract. Email, roles, orgs, all of it is
app data, reachable through `identity_extras()` or your own store.

The resolver's input needed a public shape, and here the codebase had
already answered a question the design doc treated as open. Resolvers
never saw a request object; they always got a small dict built in one
place: remote address, cookies, headers, scheme. Freezing that as
`ResolverEvent` was a typing exercise, not a design fork. The narrow
contract had been there all along, unnamed.

What used to be shipped providers is now generated code. `fymo generate
auth` renders a resolver, a store, remote endpoints, and a `users` table
schema into your app, where you can read all of it and edit any of it.
`fymo new` runs the password variant by default, so a fresh project still
reaches a working login in zero steps, which was the one guarantee the
old model had earned and the one thing I refused to regress.

## What Building It Actually Caught

The route-level `require_auth` enforcement shipped with a hole I am glad
was found before anyone else could. Declared routes carried the flag, but
the convention router happily served the same controller under alias
paths, `/dashboard/index`, `/home`, with the flag stripped. Anonymous
readers of protected pages, verified end to end. The fix makes the
protection travel with the controller, since that is the boundary the
renderer actually keys on, and the aliases now inherit the most
restrictive declaration.

The sidecar taught a quieter lesson. It is one long-lived Node process,
and the per-render identity global has to be reset unconditionally, not
just when an identity is present. The code was right, but no test proved
it, and a one-line regression would have rendered one user's name into
the next user's anonymous page. There is now a test that renders signed
in, then anonymous, then as someone else, through a single sidecar.

The plan also said to keep `session.py`. The evidence said otherwise:
every consumer of the old session-token helpers died with the model, and
the generated code mints its cookies through the public signing
primitive. Keeping a dead module because a document listed it under
"kept" is exactly the kind of decision this project exists to refuse.

## The Exit

Everything went in one release. A fymo.yml that still has an `auth:`
block does not limp along on defaults; it stops at boot and at build with
the same message, and the message is the migration doc: run the
generator, delete the block, remotes keep `@require_auth`, pages use
route-level `require_auth`. Six thousand lines left the tree. The
framework no longer knows what a user is, and that is the feature.

---

*End of Journal Entry 038*
