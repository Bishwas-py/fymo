"""Demo page for `fymo.remote.Redirect` -- not part of the blog's real
content, exists so the redirect primitive has something to click through in
tests/integration/test_redirect_hydration.py."""
from app.remote.redirect_demo import go_to_login


def getContext():
    return {"go_to_login": go_to_login}


def getDoc():
    return {"title": "Redirect demo"}
