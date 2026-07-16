# Journal Entry 035: The Framework That Couldn't Serve a Font

**Date**: July 16, 2026
**Focus**: Binary static files, and the 500 every fresh visitor was triggering
**Status**: Shipped

## A Font File Walks Into app/static

I wanted a locally hosted font, the obvious way: drop Inter.woff2 into
app/static/fonts/, point the CSS at it. The response was a 500, "Error
reading file". A woff2 is about as plain a static file as exists, so this
smelled like something structural, and it was.

The static path read the file in binary mode, correctly, and then decoded
it as UTF-8 before handing it back. The dispatch layer one floor up
already handled bytes, it had an isinstance check doing exactly the right
thing for the /dist/ route next door. So the decode bought nothing and
cost every binary format: woff2, png, ico, jpg, all of them died on the
same line. Only text assets ever survived, and nobody had noticed because
neither example app ships a single binary static file. The todo app
doesn't even have an app/static directory. The feature had been broken
for its most common use case, probably forever, and the evidence is that
nobody ever used it.

The fix was deleting the decode and returning bytes straight through.
While in there, the cache story got its missing half: these files are
unhashed, so a one-hour Cache-Control without any validator meant a full
re-download on every expiry. Static responses now carry an ETag built
from stat's mtime and size, no file read, no content hash, and
If-None-Match comes back as a 304 with an empty body. The kind of thing
Plug.Static has done since forever; table stakes, now paid.

## The 500 Nobody Ordered

The sibling bug was louder. Hit any fymo app with a path that doesn't
exist and you got a 500: "Route 'no-such-page' not in manifest. Run
`fymo build`." Now consider that every browser on a first visit requests
/favicon.ico on its own. Every fymo app in production was emitting one
500 per fresh visitor, polluting logs and any alerting keyed on 5xx
rates, and leaking an internal dev instruction to end users while at it.

The root cause took a minute to see. There is a 404 branch in the render
path, and it looked like it should have fired. It almost never could:
convention-based routing turns nearly any one- or two-segment path into a
guessed controller, so /favicon.ico "matched" as controller favicon.ico,
sailed past the no-route check, failed the manifest lookup, and surfaced
as a server error. A routing miss dressed up as a build problem.

The distinction that fixes it: a convention guess is only real if the
build actually produced that route. Convention matches now carry a flag,
and a flagged match with no manifest entry is a 404, with the built-in
page split by mode the way fymo already splits everything. Dev gets the
hint, no route matched this path, routes are declared in fymo.yml or
config/routes.py. Prod gets a clean minimal page with zero internals. A
route the app explicitly declared but never built keeps its 500, because
a stale build is a real server problem and deserves the alarm.

## Where the Favicon Actually Lives

Which still leaves the favicon with no home. Rails serves all of public/
at the root, SvelteKit serves all of static/. fymo went the Phoenix way
instead: a fixed allowlist of the filenames browsers and crawlers request
at the root by convention, favicon.ico, favicon.svg, robots.txt, the
apple-touch-icons, site.webmanifest, browserconfig.xml, plus the
.well-known/ prefix for ACME challenges and security.txt and the rest of
that long tail. Each resolves into app/static through the same traversal
guard and the same now-binary-correct serving. Nothing else in app/static
is exposed at the root by accident, and there's a test pinning that.

Precedence mattered enough to pin too: app raw routes win over the
allowlist, which wins over the 404. That ordering is what keeps a dynamic
robots.txt possible, an http_routes() entry for /robots.txt naturally
shadows the static file. And the scaffold now teaches the convention the
way conventions should be taught: `fymo new` ships a small favicon.svg
and the link tag in a root layout, so a fresh project serves its own icon
before its author has thought about icons at all.

## The Honest Footnote

The two bugs shipped together because they were the same lesson from two
angles. A framework's unglamorous paths, the static file, the unknown
route, are the ones every single visitor exercises before they see a
single feature. Both had been wrong since early days, and both were
invisible because the example apps never walked them. The example apps
are now not the only thing walking them; the test suite requests a woff2
with real font bytes in it and checks the body came back identical.

---

*End of Journal Entry 035*
