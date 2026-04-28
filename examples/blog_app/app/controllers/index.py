"""Home page controller."""
from app.remote.posts import get_posts


def getContext():
    posts = get_posts()
    return {
        "hero": posts[0] if posts else None,
        "posts": posts[1:] if len(posts) > 1 else [],
    }


def getDoc():
    return {
        "title": "Fymo Blog",
        "head": {
            "meta": [
                {"name": "description", "content": "A demo blog showing off Fymo's remote functions"},
            ]
        },
    }
