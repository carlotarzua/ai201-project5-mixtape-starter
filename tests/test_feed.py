"""Tests for Friends Listening Now feed logic."""

import pytest
from datetime import datetime, timedelta, timezone

from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_listening_now_excludes_stale_activity(app):
    """
    A friend who listened 10 minutes ago should appear,
    while a friend who listened 2 hours ago should not.
    """
    with app.app_context():
        current_user = User(
            username="current",
            email="current@example.com",
        )
        recent_friend = User(
            username="recent_friend",
            email="recent@example.com",
        )
        stale_friend = User(
            username="stale_friend",
            email="stale@example.com",
        )

        db.session.add_all([
            current_user,
            recent_friend,
            stale_friend,
        ])
        db.session.flush()

        # Create bidirectional friendships.
        for friend in [recent_friend, stale_friend]:
            db.session.execute(
                friendships.insert().values(
                    user_id=current_user.id,
                    friend_id=friend.id,
                )
            )
            db.session.execute(
                friendships.insert().values(
                    user_id=friend.id,
                    friend_id=current_user.id,
                )
            )

        recent_song = Song(
            title="Recent Song",
            artist="Recent Artist",
            shared_by=recent_friend.id,
        )
        stale_song = Song(
            title="Stale Song",
            artist="Stale Artist",
            shared_by=stale_friend.id,
        )

        db.session.add_all([recent_song, stale_song])
        db.session.flush()

        now = datetime.now(timezone.utc)

        db.session.add(
            ListeningEvent(
                user_id=recent_friend.id,
                song_id=recent_song.id,
                listened_at=now - timedelta(minutes=10),
            )
        )

        db.session.add(
            ListeningEvent(
                user_id=stale_friend.id,
                song_id=stale_song.id,
                listened_at=now - timedelta(hours=2),
            )
        )

        db.session.commit()

        results = get_friends_listening_now(current_user.id)
        usernames = [item["friend"]["username"] for item in results]

        assert "recent_friend" in usernames
        assert "stale_friend" not in usernames
