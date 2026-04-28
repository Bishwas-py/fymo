"""Seed posts from app/posts/*.md into SQLite on first run."""
import re
from datetime import datetime
from pathlib import Path
import mistune
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer

from app.lib.db import get_db


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_block, body = m.group(1), m.group(2)
    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"\'')
    return meta, body


class _PygmentsRenderer(mistune.HTMLRenderer):
    def block_code(self, code: str, info: str | None = None) -> str:
        try:
            lexer = get_lexer_by_name(info or "text", stripall=False)
        except Exception:
            lexer = guess_lexer(code)
        formatter = HtmlFormatter(noclasses=True, style="monokai")
        return highlight(code, lexer, formatter)


_md = mistune.create_markdown(renderer=_PygmentsRenderer())


def ensure_seeded(project_root: Path) -> None:
    """If posts table is empty, seed from app/posts/*.md."""
    db = get_db()
    if db.fetchone("SELECT 1 FROM posts LIMIT 1"):
        return
    posts_dir = project_root / "app" / "posts"
    if not posts_dir.is_dir():
        return
    for md_path in sorted(posts_dir.glob("*.md")):
        text = md_path.read_text()
        meta, body = _parse_frontmatter(text)
        slug = meta.get("slug") or md_path.stem
        title = meta.get("title") or slug.replace("-", " ").title()
        summary = meta.get("summary") or ""
        tags = meta.get("tags") or ""
        published_at = meta.get("published_at") or datetime.utcnow().isoformat()
        content_html = _md(body)
        db.execute(
            "INSERT OR REPLACE INTO posts (slug, title, summary, content_html, tags, published_at) VALUES (?, ?, ?, ?, ?, ?)",
            [slug, title, summary, content_html, tags, published_at],
        )
