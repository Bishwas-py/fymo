# Journal Entry 043: The Show Page That Could Not Be a Second Entry

**Date**: July 21, 2026
**Focus**: full CRUD in generated resources: get/update/delete, show pages, honest detail routing
**Status**: Shipped

## Half a Resource

The daily-loop generators shipped with list and create and quietly
called that a resource. Rails would laugh. A resource you cannot read
by id, edit, or delete is a guestbook. So: get, update, delete in the
generated remote module, a detail page, and the authorization rules I
actually believe in, generated as code people will copy.

The rule worth writing down: update and delete answer NotFound for an
unknown id and for a row the caller does not own, identically, never a
distinguishable Forbidden, because a 403 on someone else's id confirms
the id exists. One comparison against created_by does the ownership
check. And the seed row stays owned by "seed", a uid no session will
ever have, which is what makes the generated tests honest: the
signed-in test caller genuinely cannot touch it, no fixture theater.

## One Directory, One Entry

The plan for the detail page read simply: emit show.svelte next to
index.svelte, the resources convention already maps /name/id onto it.
The router half-agrees: a resources entry expands /name/:id to action
show, template name/show.svelte, id in params. Then I read the build
instead of trusting the route table. Discovery takes one entry per
template directory, index.svelte winning over show.svelte, and the
sidecar renders by route name alone; the template field in the route
info is never consulted on that path. The blog app never noticed
because its posts directory has only show.svelte. Two entries in one
directory is not a thing the build can currently produce, and a
show.svelte sitting unbuilt next to an index would be exactly the kind
of dead file a generator must never emit.

So the generated show page is a co-located component. The controller
accepts the route's id and threads it down as a prop, empty on the
index; index.svelte branches on it and mounts show.svelte, which loads
the row through get, offers the owner an edit form and a delete, and
reads as plain read-only for everyone else. Server-rendered directly,
soft-nav updates it through the same prop. And the injection had to
move too: the plain `name: name.index` route I was proudly injecting
covers exactly one URL, so a generated resource now lands in the
resources list instead, starting one when the block lacks it, with the
same parse-back-and-compare verification before a byte is written.

One more honesty check landed alongside: generating a resource into a
project with no app/auth/ now says out loud that every mutation will
answer 401 until `fymo generate auth` runs, instead of leaving a create
form pointing at a signin page that does not exist.

---

*End of Journal Entry 043*
