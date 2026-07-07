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

<!-- Add one complete RCA entry per fixed bug. -->

---

## Final Review

### Git Log

<!-- Insert screenshot of: git log --oneline -->
