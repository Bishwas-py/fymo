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
from pathlib import Path
from typing import Mapping

_TOKEN_RE = re.compile(r"__fymo_tmpl_[a-z0-9_]+?__")

PACKAGED_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def load_template(project_root: Path, rel: str) -> str:
    """Template text for `rel`, honoring project overrides.

    Lookup order: <project>/.fymo/templates/<rel> wins over the template
    packaged inside fymo (fymo/cli/templates/<rel>). `fymo generate
    templates` publishes the packaged tree into .fymo/templates/ for
    editing; tokens and the conflict writer behave identically either way.
    """
    override = Path(project_root) / ".fymo" / "templates" / rel
    if override.is_file():
        return override.read_text()
    return (PACKAGED_TEMPLATES_DIR / rel).read_text()


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
# and invariants are checked first; everything else runs suffix rules;
# a name that is not plural-shaped passes through unchanged.
#
# The -es rules deserve a note: no suffix rule can split houses/causes
# from buses/statuses (all end in -uses), so the default for -ses/-zes
# stems restores the silent e (course, size, database) and a short list
# names the nouns whose singular really ends in the sibilant. The same
# shape applies to -oes (shoe by default, hero via the list) and to
# -ches/-shes (church by default, cache via the list).
_IRREGULAR_SINGULARS = {
    "children": "child",
    "people": "person",
    "men": "man",
    "women": "woman",
    "mice": "mouse",
    "geese": "goose",
    "feet": "foot",
    "teeth": "tooth",
    # ves nouns
    "knives": "knife",
    "wolves": "wolf",
    "leaves": "leaf",
    "lives": "life",
    "halves": "half",
    "shelves": "shelf",
    # Greek ses nouns; bases stays with base (the common web noun),
    # accepting the ambiguity with basis.
    "analyses": "analysis",
    "crises": "crisis",
    "theses": "thesis",
    "diagnoses": "diagnosis",
    "parentheses": "parenthesis",
}

_INVARIANT_NAMES = {"series", "species", "fish", "sheep", "news", "data"}

# Singulars that really end in the sibilant: buses -> bus, not "buse".
# Doubles as a passthrough so the singular itself never gets clipped.
_SIBILANT_SINGULARS = {
    "bus", "status", "virus", "bonus", "gas", "lens",
    "alias", "campus", "atlas", "canvas",
}

# oes nouns whose singular ends in o (default keeps the e: shoes -> shoe).
_O_NOUNS = {"hero", "potato", "tomato", "echo", "veto"}

# ches nouns whose singular ends in e (default strips es: church, dish).
_E_FINAL_CH_NOUNS = {"cache", "niche", "mustache", "headache", "avalanche"}


def singularize(name: str) -> str:
    """Best-effort singular of a snake_case name; last segment only
    (blog_posts -> blog_post). Unrecognized shapes come back unchanged."""
    head, _, last = name.rpartition("_")
    prefix = f"{head}_" if head else ""
    if last in _IRREGULAR_SINGULARS:
        return prefix + _IRREGULAR_SINGULARS[last]
    if last in _INVARIANT_NAMES or last in _SIBILANT_SINGULARS:
        return name
    if last.endswith("ies") and len(last) > 3:
        return prefix + last[:-3] + "y"
    if last.endswith("oes"):
        stem = last[:-2]
        return prefix + (stem if stem in _O_NOUNS else last[:-1])
    if last.endswith("es"):
        stem = last[:-2]
        if stem in _SIBILANT_SINGULARS:
            return prefix + stem
        if stem.endswith("ss") or stem.endswith("x"):
            return prefix + stem
        if stem.endswith("zz"):
            return prefix + stem[:-1]
        if stem.endswith(("ch", "sh")):
            restored = stem + "e"
            return prefix + (restored if restored in _E_FINAL_CH_NOUNS else stem)
        if stem.endswith(("s", "z")):
            return prefix + stem + "e"
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
