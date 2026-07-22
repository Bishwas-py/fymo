# Journal Entry 044: A Grammar, a Reverse Gear, and an Escape Hatch

**Date**: July 22, 2026
**Focus**: singular API names, fymo destroy, component/layout/broadcast generators, overridable templates, honest read-only fallback
**Status**: Shipped

## The Generator Learns English

`generate resource posts` used to emit create_posts and get_posts,
functions that create and fetch exactly one row while wearing a plural
name. Rails solved this two decades ago with an inflector, so fymo got
a small one: irregulars first, invariants passed through, then three
suffix rules, applied to the last snake segment only, with anything not
plural-shaped left alone. The part I sweated was the guard rails, not
the happy path: status must not become statu, address must not become
addres, analysis stays whole. A thirty-case battery pins it. Now the
collection keeps the plural (list_posts) and every per-row verb speaks
singular (get_post, update_post), with the TypedDict named BlogPost
when the resource is blog_posts.

## Reverse Gear

Generation without destruction is a one-way ratchet, and one-way
ratchets make people afraid to try things. `fymo destroy` inverts the
generators with the same brand of caution they write with: it renders
the current templates pristine, deletes only files that are still
byte-identical to that render, and refuses all or nothing on anything
modified since generation, naming each file, unless --force. Route
removal reuses the injection guard in reverse, the edit only lands
when the reparsed fymo.yml equals the old mapping minus exactly the
one entry. The snapshot tests are the proof I wanted: generate then
destroy leaves the project tree byte-identical, for pages, remotes,
resources, and the read-only variant. The two deliberate asymmetries
are shared surface: tests/conftest.py survives even when generation
wrote it, and app/remote/ only goes when the destroyed module was the
last one living there.

## The Escape Hatch, and an Honest No

Two closing moves. Templates became overridable: .fymo/templates/<same
path> wins over the packaged file, `fymo generate templates` publishes
the tree for editing, and because destroy compares against the same
lookup, an overridden template still round-trips cleanly. And the
no-auth warning became a real answer: a project without app/auth/ used
to get full CRUD plus a paragraph explaining why none of the mutations
would ever work, a create form pointing at a signin page that did not
exist. Now it gets the read-only variant, list and get, a page without
the form, and one sentence saying exactly how to upgrade. Generating
code you know is dead and apologizing for it in a warning was the
worst of both worlds; either the machinery exists or the generator
should not pretend it does.

Component, layout, and broadcast generators round out the set, the
broadcast one written only after reading the discovery walker and the
old blog example, because its convention (signature is the subscribe
args, return annotation is the payload, body is the guard) is exactly
the kind of thing a generator exists to teach.

---

*End of Journal Entry 044*
