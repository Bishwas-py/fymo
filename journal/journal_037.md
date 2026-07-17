# Journal Entry 037: The Magic Filename and the URL That Lied

**Date**: July 16, 2026
**Focus**: app/assets, layouts importing their own CSS, and /assets/ becoming /static/
**Status**: Shipped

## Where Fonts Actually Go

Entry 035 ended with a woff2 finally serving out of app/static, byte-exact.
That fixed serving a font. It did nothing for building with one. Write the
obvious CSS, `@font-face { src: url('./inter.woff2') }`, and the build died
on the spot: esbuild had no loaders configured, so a binary file referenced
from a stylesheet wasn't slow or wrong, it was impossible. A framework that
compiles CSS but can't compile the font that CSS points at has answered
the "where do fonts go" question with "nowhere."

The answer is now a directory with a one-line contract. Everything in
app/assets/ is a compiler input: consumed by esbuild, content-hashed into
/dist/, never served raw. Fonts live next to the CSS that references them,
because they are the same kind of thing, build inputs, not page templates
and not verbatim files. It's Rails's mental model, app/assets in, public
out, and it took embarrassingly long to steal it.

## Global Was Never a Framework Concept

The other half of the CSS story was a magic filename. app/templates/
_global.css: silently detected, silently bundled as its own entry, silently
linked into every page. It worked, and like every ugly thing that works it
had grown roots, a has_global_css flag in the build config, a special case
in the metafile matching, a field in the manifest, an injection in the HTML
builder. Four pieces of plumbing for one file nobody ever declared.

Meanwhile the layout system had already built the honest version without
noticing. Layouts are build entries. Their CSS is tracked in the manifest,
because component style blocks already compile to external css files. So
the entire replacement is one line in the root layout's script:

    import '../assets/app.css';

esbuild bundles imported CSS into that entry's sibling CSS output, which
the manifest already carries. A page links the union of its layout chain's
CSS, root first, then its own. "Global" stops being framework vocabulary:
it is whatever the root layout imports, and a section layout imports only
what it adds on top, so admin.css rides only the admin pages. The four
pieces of plumbing are deleted, not deprecated. A project still shipping
_global.css fails the build with the exact fix in the error text, move it,
import it, done. And since stylesheets now have one home, a loose .css
anywhere under app/templates/ is a build error too. The directory contract
is two words now: svelte only.

The loaders themselves are the boring part, which is the compliment. File
loaders for the font and image extensions, publicPath pointing at
/dist/client/ so the rewritten urls resolve where dist actually serves, the
same assetNames hashing the bundles already used. Root-absolute /static/
urls are marked external and pass through untouched, because those are
references to verbatim files, not build inputs. The SSR pass empty-loads
.css so the node bundle doesn't choke on the layout's import. And a
fontsource-style `@import '@fontsource/inter'` resolves through the
project's own node_modules; the test fakes the package locally, a
package.json whose main points at an index.css, which is all fontsource is.

## The URL That Lied

None of this naming works while the serving URL contradicts it. Files in
app/static/ were served at /assets/, a directory named static behind a URL
named assets, a wart old enough to feel like furniture. app/assets/ turned
the wart into a collision: in one css file, '../assets/app.css' would have
meant build input while url('/assets/logo.png') meant verbatim static file.
Same word, opposite meanings, one line apart.

So the URL now tells the truth. /static/ serves app/static/, through the
same traversal guard and the same binary-correct, ETag-validated path 035
fixed. /assets/ doesn't redirect and doesn't dual-serve, it simply stops
existing; requests fall through to routing and hit the clean 404. Grepping
an app for /assets/ is the entire migration guide.

Deleting the old branch turned up a corpse worth noting. The /assets/css/
path served CSS from an in-memory dict that nothing had written to in the
hashed-dist era, the store method had zero callers, so the branch could
never once have produced a byte. It's gone, not renamed. Dead code that
moves house just dies somewhere newer.

## The Honest Footnote

One duplication is left standing, deliberately. A route's own bundle also
reaches the layout component (the hydration shell imports it), so the
layout's imported CSS lands in the route's css file as well as the
layout's. Linking both means the same rules can arrive twice. CSS is
idempotent and the files are cached immutably, so nothing breaks and
nothing renders wrong, but if bundle budgets ever get tight, that's where
the easy kilobytes are hiding. Written down here so future me doesn't get
to discover it twice.

---

*End of Journal Entry 037*
