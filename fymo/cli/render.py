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


# English inflection, heuristic and stdlib-only: enough for generated
# API names to read grammatically (get_post, not get_posts). Irregulars
# and invariants are checked first; everything else runs three suffix
# rules; a name that is not plural-shaped passes through unchanged.
_IRREGULAR_SINGULARS = {
    "children": "child",
    "people": "person",
    "men": "man",
    "women": "woman",
    "mice": "mouse",
    "geese": "goose",
    "feet": "foot",
    "teeth": "tooth",
}

_INVARIANT_NAMES = {"series", "species", "fish", "sheep", "news", "data"}

_SIBILANT_ENDINGS = ("s", "x", "z", "ch", "sh")


def singularize(name: str) -> str:
    """Best-effort singular of a snake_case name; last segment only
    (blog_posts -> blog_post). Unrecognized shapes come back unchanged."""
    head, _, last = name.rpartition("_")
    prefix = f"{head}_" if head else ""
    if last in _IRREGULAR_SINGULARS:
        return prefix + _IRREGULAR_SINGULARS[last]
    if last in _INVARIANT_NAMES:
        return name
    if last.endswith("ies") and len(last) > 3:
        return prefix + last[:-3] + "y"
    if last.endswith("es") and last[:-2].endswith(_SIBILANT_ENDINGS):
        return prefix + last[:-2]
    if last.endswith("s") and not last.endswith(("ss", "us", "is")):
        return prefix + last[:-1]
    return name


def _title(name: str) -> str:
    return name.replace("_", " ").title()


def name_variants(name: str) -> dict:
    """Derive every token variant generators need from one name.

    `name` is the snake_case name as given; `name_title` is its
    title-cased form with underscores as spaces (posts -> Posts,
    blog_posts -> Blog Posts); the singular variants carry the
    grammatical forms for per-item names (name_singular_class is the
    CamelCase type name, blog_posts -> BlogPost). Add variants only
    when a template actually uses them.
    """
    singular = singularize(name)
    return {
        "name": name,
        "name_title": _title(name),
        "name_singular": singular,
        "name_singular_title": _title(singular),
        "name_singular_class": "".join(part.capitalize() for part in singular.split("_")),
    }
