# Journal Entry 042: The Framework That Hand-Typed Its Own Daily Loop

**Date**: July 21, 2026
**Focus**: generate page, generate remote, generate resource, on one renderer and one writer
**Status**: Shipped

## One Generator, For a Once-Per-Project Event

Took honest stock of the scaffolding story and the ranking was
uncomfortable: the philosophy was the best part, the toolbox was the
missing part. `fymo generate auth` had the ownership model exactly
right, inert templates, verbatim copies, refuse-to-overwrite, generated
code belongs to the app. And it runs once per project. Meanwhile the
thing I do every single day, add a page, add a remote module, wire the
route, write the test, was four hand-typed files whose shapes the
framework knows perfectly and typed for nobody. Worse, the repo had two
scaffolding mechanisms: auth read template files, while `fymo new`
carried its entire scaffold as 540 lines of Python string literals.
One codebase, two ways to render the same kind of thing, and the
`.tmpl` files were not even templates, just files with a suffix that
promised parameterization nobody had built.

## The Marker That Already Meant Something

The renderer needed markers that can never occur in Svelte, JS, or
Python content by accident. Dollar-based templating was dead on
arrival, the content is wall-to-wall `$props`, `$derived`, `$auth`. My
first sketch was `__fymo_name__`, dunder-wrapped, identifier-safe, no
brace or dollar anywhere. Then a grep before committing turned up
`__fymo_remote__` and `__fymo_require_auth__`: real attribute names the
decorators stamp on functions, already living in exactly that
namespace, one comment away from appearing inside a template. A
renderer that treats every `__fymo_*__` as a token would fail loudly on
legitimate prose about the framework's own markers. So tokens are
`__fymo_tmpl_*__`, a namespace nothing else uses; unknown tokens inside
it raise with the token's name, everything outside it passes through
untouched. That untouched property is load-bearing: a template with no
tokens renders byte-identical, which is what let `generate auth` and
then all of `fymo new` move onto the shared renderer with a sha256
fixture pinning every scaffold file, captured from the inline-literal
code before the first line moved.

## The Routes File That Wasn't There

The plan said route injection targets config/routes.py, and the router
disagreed. FymoApp reads fymo.yml first and falls back to
config/routes.py only when fymo.yml is absent, and every scaffolded
project has a fymo.yml, so an entry written to config/routes.py would
be dead the moment it landed. The injection went where the routes
actually live. The policy is deliberately narrow: anchor on the one
block-form `routes:` line the scaffold produces, insert the single
entry, re-parse, and accept the edit only if the result equals the old
mapping plus exactly the new route. Any file that drifted from that
shape gets the exact line to add printed instead, with the generated
files intact and a zero exit. The failure mode I refused to ship is the
half-write: a generator that mangles your config teaches you to never
run it again.

The bar was one sentence, so it became one test: new project, generate
resource twice (one name already routed by the scaffold's resources
entry, one injected fresh), a real build, both pages rendering 200
through the server, and the generated tests passing under an actual
pytest run in the app directory. The generated test file is the part I
like most: it leans on fymo.testing's signed_in the way the blog app's
tests do, so the first thing a fresh resource teaches you is how to
prove your own auth boundaries.

---

*End of Journal Entry 042*
