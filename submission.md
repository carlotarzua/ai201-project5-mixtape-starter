# Mixtape Bug Hunt Submission

## AI Usage

I used ChatGPT to help me understand the structure of the unfamiliar codebase, trace routes to service functions, and explain suspicious conditions after I located them. I also used AI to help compare working and broken code paths and to organize my root cause analysis. I verified conclusions by reading the code myself, running the existing tests, reproducing bugs with the seeded data, and rerunning tests after each fix.

One important example of verification was the search issue. The project describes a duplicate-search bug, but the existing search tests passed in my local environment. Because I could not reproduce that issue, I did not claim it as one of my fixes.

---

## Codebase Map

### Main Files and Responsibilities

* `app.py` creates and configures the Flask application, initializes SQLAlchemy, registers the route blueprints, and creates database tables.
* `models.py` defines the SQLAlchemy database models, including `User`, `Song`, `Tag`, `ListeningEvent`, `Rating`, `Playlist`, and `Notification`. It also defines association tables for friendships, song tags, and ordered playlist entries.
* `seed_data.py` resets and populates the database with test users, friendships, songs, tags, listening events, playlists, and notifications.
* `routes/songs.py` handles song search, song details, rating songs, and recording listening events.
* `routes/playlists.py` handles playlist creation, playlist retrieval, retrieving playlist songs, and adding songs to playlists.
* `routes/users.py` handles user profiles, streak retrieval, notification retrieval, and marking notifications as read.
* `routes/feed.py` handles the “Friends Listening Now” feed and general friend activity feed.
* `services/streak_service.py` records listening events and updates user listening streaks.
* `services/feed_service.py` builds the recent listening feed and the general activity feed.
* `services/search_service.py` searches for songs and retrieves individual songs.
* `services/notification_service.py` creates and retrieves notifications and contains the workflows for rating songs and adding songs to playlists.
* `services/playlist_service.py` creates playlists and retrieves playlist metadata and ordered playlist songs.
* `tests/` contains tests for streak behavior, search behavior, and playlist retrieval.

### Example Data Flow: Rating a Song

1. A client sends `POST /songs/<song_id>/rate`.
2. `routes/songs.py` reads `user_id` and `score` from the JSON request.
3. The route calls `notification_service.rate_song(user_id, song_id, score)`.
4. `rate_song()` validates the score and checks that both the song and user exist.
5. It checks whether the user already rated the song.
6. It either updates the existing `Rating` or creates a new `Rating`.
7. The service commits the database changes.
8. The route converts the returned rating to a dictionary and sends it as JSON.

### Pattern I Noticed

The application separates HTTP handling from business logic. Route files mainly parse request data, call service functions, and format JSON responses. The service layer contains the main application behavior and database queries. This is why a visible endpoint bug often requires tracing from the route into the corresponding service file.

The data model also uses association tables for many-to-many relationships. For example, `playlist_entries` connects playlists and songs while also storing `position`, `added_by`, and `added_at`, so playlist ordering is explicit rather than relying on normal database insertion order.

---

## Root Cause Analyses

### Issue #1 — My Listening Streak Keeps Resetting

**How I reproduced it:**  
I first ran `pytest tests/` before changing any code. The test `test_streak_increments_on_sunday` failed. The test simulated a user listening on Saturday, June 15, 2024 and then again on Sunday, June 16, 2024. The streak stayed at 1 instead of increasing to 2. I then ran `pytest tests/test_streaks.py` after the fix and all 5 streak tests passed.

**How I found the root cause:**  
I traced the listening flow from `routes/songs.py`, where the `/songs/<song_id>/listen` endpoint calls `record_listening_event()`, into `services/streak_service.py`. Inside `update_listening_streak()`, I looked at the conditions that compare the current date with `last_listened_at`. The important line was `elif days_since_last == 1 and today.weekday() != 6:`. I verified that Python's `weekday()` uses 6 for Sunday. That made me confident this was the exact cause because the code explicitly prevented the normal consecutive-day increment on Sundays, matching the failing Saturday-to-Sunday test.

**The root cause:**  
The streak logic treated Sunday differently from every other consecutive day. When exactly one day had passed, the streak incremented only if `today.weekday() != 6`. Since Sunday has a `weekday()` value of 6, a user who listened on Saturday and again on Sunday did not enter the increment branch. Instead, execution fell into the `else` branch and reset the streak to 1 even though the listens happened on consecutive calendar days.

**My fix and side-effect check:**  
I removed the unnecessary Sunday condition and changed the branch to `elif days_since_last == 1:`. This makes every consecutive calendar day increment the streak, including Saturday to Sunday. I reran `pytest tests/test_streaks.py` and all 5 tests passed. I also checked the related behaviors covered by the suite: a new user starts at 1, listening twice on the same day does not double count, normal consecutive days increment, and skipping a day resets the streak.

### Issue #5 — The Last Song in a Playlist Never Shows Up

**How I reproduced it:**  
Before changing any code, I ran `pytest tests/`. The tests `test_playlist_returns_all_songs` and `test_playlist_returns_songs_in_order` both failed. The test playlist contained 5 songs, but `get_playlist_songs()` returned only 4. The returned titles stopped at `Track 4`, so `Track 5`, the final song, was missing. After applying the fix, I ran `pytest tests/test_playlists.py` and all 3 playlist tests passed.

**How I found the root cause:**  
I traced the playlist retrieval flow from `routes/playlists.py`, where the `GET /playlists/<playlist_id>/songs` route calls `get_playlist_songs()`, into `services/playlist_service.py`. The SQLAlchemy query correctly joined the playlist entries, filtered by playlist ID, ordered the songs by position, and called `.all()`. I then inspected the return statement and found `songs[:-1]`. This made me confident I had found the exact cause because Python slicing with `[:-1]` returns every element except the last one, which exactly matched the observed behavior of a 5-song playlist returning 4 songs.

**The root cause:**  
The database query retrieved the complete ordered list of songs, but the return statement intentionally sliced that list with `songs[:-1]`. In Python, that slice excludes the final element. As a result, every non-empty playlist lost its last song during response construction even though the database query had retrieved it correctly.

**My fix and side-effect check:**  
I changed the return statement from iterating over `songs[:-1]` to iterating over the complete `songs` list. This preserves every retrieved song while keeping the existing database ordering unchanged. I reran `pytest tests/test_playlists.py` and all 3 tests passed. I also checked that the returned songs remained in position order and that an empty playlist still returned an empty list.

---

### Issue #2 — Friends Listening Now Shows Stale Activity

**How I reproduced it:**
Before changing any code, I used the seeded database and called `get_friends_listening_now()` for the seeded user `darius`. The result included `simone`, whose event was relatively recent, but it also included `nova`, whose listening event was about 2 hours old. This confirmed that the “Listening Now” feed was including stale activity. After changing the threshold, I reran the same check and `nova` no longer appeared. By that later run, the seeded recent events had also aged beyond the new 30-minute window, so the result was empty. I therefore used a controlled regression test to verify both sides of the cutoff: a 10-minute-old event appeared, while a 2-hour-old event did not.

**How I found the root cause:**
I traced the request flow from `routes/feed.py`, where the `/feed/<user_id>/listening-now` endpoint calls `get_friends_listening_now()`, into `services/feed_service.py`. I inspected how the cutoff time was calculated and found `RECENT_THRESHOLD = timedelta(hours=24)`. The function subtracts this threshold from the current time and returns listening events newer than that cutoff. This made me confident I had found the exact cause because a 24-hour window directly explained why an event from about 2 hours earlier appeared in a feature called “Listening Now.”

**The root cause:**
The “Listening Now” feed used a 24-hour recency threshold. As a result, a friend who listened many hours earlier could still appear in the feed. The database query was filtering according to the configured cutoff, but the cutoff itself was too large for the intended live-style behavior.

**My fix and side-effect check:**
I changed `RECENT_THRESHOLD` from `timedelta(hours=24)` to `timedelta(minutes=30)`. This keeps genuinely recent listening activity while excluding stale events from hours earlier. I added a regression test in `tests/test_feed.py` that creates one friend with a listening event from 10 minutes ago and another friend with an event from 2 hours ago. The test verifies that the recent friend appears and the stale friend does not. I ran `pytest tests/test_feed.py`, which passed, and then ran the full test suite, where all 14 tests passed.

---

## Final Review

### Git Log

<!-- Insert screenshot of: git log --oneline -->
