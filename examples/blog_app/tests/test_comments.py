"""Comment authorship comes from the authenticated session, never from
client input. fymo.testing simulates the sessions: signed_in() for the
first caller, acting_as() to switch to a second user mid-test."""
from fymo.testing import acting_as, make_user, signed_in


def _seed_post(db, slug="hello-world"):
    db.execute(
        "INSERT INTO posts (slug, title, summary, content_html, tags, published_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [slug, "Hello World", "intro post", "<p>hi</p>", "intro", "2026-01-01T00:00:00Z"],
    )
    return slug


def test_authenticated_comment_is_attributed_to_the_session_user(db):
    from app.remote.posts import NewComment, create_comment

    slug = _seed_post(db)
    alice = make_user(email="alice@example.com")
    with signed_in(alice):
        comment = create_comment(slug, input=NewComment(body="first!"))
    assert comment["name"] == "alice"


def test_second_user_cannot_comment_as_the_first(db):
    from app.remote.posts import NewComment, create_comment, get_comments

    slug = _seed_post(db)
    alice = make_user(email="alice@example.com")
    bob = make_user(email="bob@example.com")

    with signed_in(alice):
        create_comment(slug, input=NewComment(body="alice's take"))
        with acting_as(bob):
            bobs_comment = create_comment(slug, input=NewComment(body="bob's reply"))
        assert bobs_comment["name"] == "bob"

        comments = get_comments(slug)
    assert {c["name"] for c in comments} == {"alice", "bob"}

    rows = db.fetchall("SELECT name, uid FROM comments ORDER BY name")
    uids = {row["name"]: row["uid"] for row in rows}
    assert uids["alice"] != uids["bob"]


def test_users_have_isolated_reactions(db):
    from app.remote.posts import toggle_reaction

    slug = _seed_post(db)
    alice = make_user(email="alice@example.com")
    bob = make_user(email="bob@example.com")

    with signed_in(alice):
        counts = toggle_reaction(slug, "clap")
        assert counts["clap"] == 1
        with acting_as(bob):
            counts = toggle_reaction(slug, "clap")
        assert counts["clap"] == 2
