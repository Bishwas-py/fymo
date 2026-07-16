"""Home page controller."""
from app.remote.posts import list_posts


def getContext():
    # First page only; hero takes one slot. The template loads the rest
    # through the list_posts remote callable threaded as a prop.
    page = list_posts(limit=11)
    posts = page["items"]
    return {
        "hero": posts[0] if posts else None,
        "posts": posts[1:] if len(posts) > 1 else [],
        "next_cursor": page["next_cursor"],
        "list_posts": list_posts,  # remote callable threaded as prop
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
