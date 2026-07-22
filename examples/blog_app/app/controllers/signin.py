"""Signin page controller.

The route named signin is auto-public and is where anonymous visitors are
redirected when a `require_auth: true` route turns them away. The form
lives in app/templates/signin/index.svelte.

The remote functions from app/remote/auth.py are threaded to the template
as props: on the client each becomes a typed fetch wrapper hitting the
real endpoint.
"""

from app.remote.auth import login, signup


def getContext():
    return {
        'title': 'Sign in',
        'login': login,
        'signup': signup,
    }
