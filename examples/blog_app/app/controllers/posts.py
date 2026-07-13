"""Post detail controller. Receives slug as `id` from the resource route."""
from app.remote.posts import get_post, get_comments, get_reactions, create_comment, toggle_reaction


def getContext(id: str = ""):
    post = get_post(id)
    return {
        "post": post,
        "initial_comments": get_comments(id),
        "initial_reactions": get_reactions(id),
        "create_comment": create_comment,    # remote callable threaded as prop
        "toggle_reaction": toggle_reaction,  # remote callable threaded as prop
    }


def getDoc():
    return {"title": "Post"}
