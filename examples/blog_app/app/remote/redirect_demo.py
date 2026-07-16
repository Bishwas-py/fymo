"""Demo remote function exercising `fymo.remote.Redirect` end to end -- see
tests/integration/test_redirect_hydration.py, which drives this through the
real compiled client bundle (not just checking the server's JSON)."""
from fymo.remote import remote, Redirect


@remote
def go_to_login() -> None:
    raise Redirect("/login")
