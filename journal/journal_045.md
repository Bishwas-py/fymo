# Journal Entry 045: The Framework Eats Its Own Output

**Date**: July 22, 2026
**Focus**: examples/blog_app and examples/todo_app replaced with pure generator output
**Status**: Shipped

## The Examples Were Lying About the Framework

Both examples predated the generators and said so on every screen: a
todo page written before layouts existed, a blog with its own database
helper, its own pagination, its own auth wiring from three reworks ago.
Anyone reading them learned a fymo that no longer exists. So they died
and came back as nothing but commands: fymo new plus generate resource
posts plus generate remote comments for the blog, fymo new plus
generate resource todos for the other, zero hand edits. If the examples
now embarrass us, the generators embarrass us, and that pressure
pointing at the right code is the whole point of dogfooding.

A small cleanup rode along: the tracked node_modules symlinks that git
kept materializing over real installs during branch switches. The root
cause was one character. The ignore pattern said node_modules/ and the
trailing slash matches directories only, so a node_modules SYMLINK
sailed past it and got committed. Slash deleted, symlinks untracked.

## What the Old Tests Were Actually Holding

The real work was the suite: eighty failures, every one a place where a
framework test had quietly become a test of example content. Migrating
them forced an honest sort into three piles. Tests that only needed new
markers (the todo body class, the root route, manifest names) were
repointed. Tests whose subject the old example happened to provide,
pagination through real dispatch, a broadcast guard body, the redirect
demo page, the alias negative controls, now write their own small
fixture onto the copy, which is where those probes always belonged: the
framework seam is theirs, the example was just a convenient host. And
one test died honestly: the db-concurrency regression pinned the old
blog's own sqlite helper, app code fymo never shipped, and deleting it
cost the framework nothing.

Two of the migrations taught me something. The sidecar tests had been
passing bare props for years because the old todo app had no layout;
the moment the example gained the scaffold's root layout, every direct
render needed the real leafProps/layoutProps shape, which means the
tests now exercise what production actually sends. And the old
getDoc-calling template was doing silent double duty as the doc-seam
fixture, so that seam nearly lost its only coverage; it kept it through
a five-line probe template the test now owns. The suite ends at 1427
green, one honest test lighter, with both examples building, serving,
and passing their own generated tests from a cold checkout.

---

*End of Journal Entry 045*
