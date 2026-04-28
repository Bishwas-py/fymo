"""Tag-filtered list."""
from app.remote.posts import get_posts


def getContext(id: str = ""):
    all_posts = get_posts()
    filtered = [p for p in all_posts if id in (p.get("tags") or "").split(",")]
    return {"tag": id, "posts": filtered}


def getDoc():
    return {"title": "Tag"}
