"""Token renderer for generator templates. Stdlib only.

Markers look like `__fymo_tmpl_name__`. The shape is chosen so a marker
can never occur in real template content by accident:

- identifier characters only, so it cannot collide with Svelte runes
  ($props, $derived), template expressions ({expr}), JS template
  literals (`${x}`), or Python f-strings, which rules out
  string.Template and every $/{}-based scheme;
- the `__fymo_tmpl_` stem is disjoint from the runtime `__fymo_*__`
  marker attributes (__fymo_remote__, __fymo_require_auth__, ...), which
  are legitimate content in generated code and its comments.

A template with no markers renders byte-identical, which is what lets
verbatim-copy generators share this renderer without their output
changing. A marker whose key is not in the provided tokens raises
UnknownTokenError instead of passing through silently.
"""
import re
from typing import Mapping

_TOKEN_RE = re.compile(r"__fymo_tmpl_[a-z0-9_]+?__")


class UnknownTokenError(ValueError):
    """A template contains a `__fymo_tmpl_*__` marker with no matching token."""


def render(text: str, tokens: Mapping[str, str]) -> str:
    """Substitute `__fymo_tmpl_<key>__` markers with `tokens[<key>]`.

    Tokens without a matching marker are ignored (generators pass one
    shared variant dict to every template). Any marker left after
    substitution raises UnknownTokenError naming it.
    """
    for key, value in tokens.items():
        text = text.replace(f"__fymo_tmpl_{key}__", value)
    leftover = sorted(set(_TOKEN_RE.findall(text)))
    if leftover:
        raise UnknownTokenError(
            f"unknown template token(s): {', '.join(leftover)} "
            f"(provided: {', '.join(sorted(tokens)) or 'none'})"
        )
    return text


def name_variants(name: str) -> dict:
    """Derive every token variant generators need from one name.

    `name` is the snake_case name as given; `name_title` is its
    title-cased form with underscores as spaces (posts -> Posts,
    blog_posts -> Blog Posts). Add variants only when a template
    actually uses them.
    """
    return {
        "name": name,
        "name_title": name.replace("_", " ").title(),
    }
