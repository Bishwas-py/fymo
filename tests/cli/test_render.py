"""Token renderer shared by every generator (issue #89 phase 1).

Markers are `__fymo_tmpl_<key>__`: identifier characters only, so no
overlap with Svelte runes ($props/$derived), template expressions
({expr}), JS template literals, or Python f-strings; and the stem is
disjoint from the runtime `__fymo_remote__` / `__fymo_require_auth__`
marker attributes that legitimately appear in framework and template
prose. A template with no tokens must round-trip byte-identical: that
property is what lets `fymo new` and `generate auth` move onto this
renderer without their output changing at all.
"""
from pathlib import Path

import pytest

from fymo.cli.render import UnknownTokenError, name_variants, render

TEMPLATES_ROOT = Path(__file__).resolve().parents[2] / "fymo" / "cli" / "templates"

SVELTE_HEAVY = """<script>
  import { identity } from '$auth';
  import type { Item } from '$remote/posts';

  let { title, login } = $props();
  let count = $state(0);
  let doubled = $derived(count * 2);
  const greeting = `hello ${title} __fymo_remote__`;
</script>

<h1>{title}</h1>
{#if $identity}
  <p>{doubled} {@html greeting}</p>
{/if}

<style>
  h1 { color: #ff3e00; }
</style>
"""


def test_no_token_svelte_content_round_trips_byte_identical():
    assert render(SVELTE_HEAVY, {}) == SVELTE_HEAVY


def test_no_token_render_ignores_extra_provided_tokens():
    """Generators pass one shared variant dict to every template; templates
    use only the tokens they need."""
    assert render(SVELTE_HEAVY, {"name": "posts", "name_title": "Posts"}) == SVELTE_HEAVY


def test_substitutes_every_occurrence():
    out = render(
        "title: __fymo_tmpl_name_title__\nslug: __fymo_tmpl_name__/__fymo_tmpl_name__\n",
        {"name": "posts", "name_title": "Posts"},
    )
    assert out == "title: Posts\nslug: posts/posts\n"


def test_token_embedded_in_an_identifier():
    out = render("def list___fymo_tmpl_name__():\n", {"name": "posts"})
    assert out == "def list_posts():\n"


def test_unknown_token_raises_and_names_it():
    with pytest.raises(UnknownTokenError) as excinfo:
        render("hello __fymo_tmpl_bogus__", {"name": "posts"})
    assert "__fymo_tmpl_bogus__" in str(excinfo.value)


def test_unknown_token_raises_even_with_no_tokens_provided():
    with pytest.raises(UnknownTokenError):
        render("x = '__fymo_tmpl_name__'", {})


def test_runtime_fymo_markers_are_not_tokens():
    """__fymo_remote__ / __fymo_require_auth__ are real attribute names in
    framework code; template prose mentioning them must pass through."""
    text = "wrapper.__fymo_require_auth__ = True  # like __fymo_remote__\n"
    assert render(text, {}) == text


def test_name_variants_snake_and_title():
    assert name_variants("posts") == {"name": "posts", "name_title": "Posts"}
    assert name_variants("blog_posts") == {
        "name": "blog_posts",
        "name_title": "Blog Posts",
    }


def test_every_shipped_template_without_tokens_round_trips():
    """The auth templates carry no tokens today; rendering them must be a
    byte-identical copy so wiring generators onto the renderer can never
    change their output."""
    tmpl_files = sorted(TEMPLATES_ROOT.rglob("*.tmpl"))
    assert tmpl_files, "no templates found under fymo/cli/templates/"
    variants = name_variants("sample")
    for tmpl in tmpl_files:
        text = tmpl.read_text()
        if "__fymo_tmpl_" in text:
            continue
        assert render(text, variants) == text, tmpl
