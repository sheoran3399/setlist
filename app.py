from __future__ import annotations

import os
import re
import secrets
from urllib.parse import quote

import spotipy
from flask import Flask, redirect, render_template, request, session, url_for

import claude_tagger
from config import load_config
from identify import identify_track
from soundcloud_source import list_playlist_tracks
from spotify_client import add_tracks, get_existing_track_uris, get_oauth, get_or_create_playlist

app = Flask(__name__)
# Needed to sign the session cookie that gates /spotify/login and /callback
# (see PLAYLIST_ADD_SECRET below). Falling back to a per-process random key
# is fine here -- it just means everyone's session resets on a restart --
# but set FLASK_SECRET_KEY so that doesn't happen on every redeploy.
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Playlist-adding writes to Spotify and is reachable on the public deployment
# (no per-visitor login separates "you" from a random visitor with the link),
# so /playlist, /spotify/login, and /callback are all gated behind a shared
# secret -- not just /playlist's own form check. Without gating the other
# two as well, anyone could hit /spotify/login directly, authenticate with
# their *own* Spotify account, and silently overwrite the single shared
# token cache file -- poisoning it so /playlist starts acting on the
# attacker's account instead of the owner's. Leave PLAYLIST_ADD_SECRET unset
# to disable the gate entirely (e.g. for pure local use).
PLAYLIST_ADD_SECRET = os.environ.get("PLAYLIST_ADD_SECRET", "")

_SPOTIFY_TRACK_RE = re.compile(r"(?:open\.spotify\.com/track/|spotify:track:)([A-Za-z0-9]+)")


def _is_authorized() -> bool:
    return not PLAYLIST_ADD_SECRET or session.get("playlist_authorized") is True


def _spotify_app_redirect_uri() -> str:
    # Distinct from SPOTIFY_REDIRECT_URI (the CLI's localhost callback, which
    # only works for a script running on the same machine as the browser) --
    # this one is the deployed app's own callback route.
    return os.environ.get("SPOTIFY_APP_REDIRECT_URI", "http://127.0.0.1:5050/callback")


def _get_oauth():
    config = load_config()
    return get_oauth(
        config.spotify_client_id, config.spotify_client_secret, _spotify_app_redirect_uri()
    )


def _parse_spotify_links(text: str) -> list[str]:
    """Extract track URIs from pasted Spotify links, one per line, deduped."""
    seen: set[str] = set()
    uris: list[str] = []
    for line in text.splitlines():
        match = _SPOTIFY_TRACK_RE.search(line.strip())
        if not match:
            continue
        track_id = match.group(1)
        if track_id not in seen:
            seen.add(track_id)
            uris.append(f"spotify:track:{track_id}")
    return uris


def _tag_genre_mood(artist: str | None, title: str | None) -> tuple[str | None, str | None]:
    if not (ANTHROPIC_API_KEY and artist and title):
        return None, None
    result = claude_tagger.classify(ANTHROPIC_API_KEY, artist, title)
    if not result:
        return None, None
    return result.genre, result.mood


def _spotify_search_url(artist: str | None, title: str | None) -> str | None:
    """A Spotify search deep-link, not a confirmed track link.

    Shazam (unlike AudD) never resolves a specific Spotify track ID for us,
    and resolving one ourselves would require a live Spotify API search --
    which needs Spotify credentials the web UI is deliberately built to not
    require. A search link needs no API call or auth at all.
    """
    if not (artist and title):
        return None
    return f"https://open.spotify.com/search/{quote(f'{artist} {title}')}"


def extract_track_names(soundcloud_url: str) -> list[dict]:
    """Identify every song referenced by a SoundCloud URL, no Spotify involved.

    Returns one dict per identified (or unidentified) item: {label, artist,
    title, matched, spotify_url, genre, mood}. DJ sets expand into multiple
    items (one per confirmed song); ordinary tracks yield exactly one.
    """
    config = load_config()
    sc_tracks = list_playlist_tracks(soundcloud_url)

    results = []
    for sc_track in sc_tracks:
        for label, _recognition, artist, title in identify_track(sc_track, config):
            if title:
                genre, mood = _tag_genre_mood(artist, title)
                results.append(
                    {
                        "label": label,
                        "artist": artist,
                        "title": title,
                        "matched": True,
                        "spotify_url": _spotify_search_url(artist, title),
                        "genre": genre,
                        "mood": mood,
                    }
                )
            else:
                results.append(
                    {
                        "label": label,
                        "artist": None,
                        "title": None,
                        "matched": False,
                        "spotify_url": None,
                        "genre": None,
                        "mood": None,
                    }
                )
    return results


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method != "POST":
        return render_template("index.html")

    soundcloud_url = request.form.get("soundcloud_url", "").strip()
    if not soundcloud_url:
        return render_template("index.html", error="Paste a SoundCloud URL first.")

    try:
        results = extract_track_names(soundcloud_url)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the page
        return render_template("index.html", error=str(exc), soundcloud_url=soundcloud_url)

    return render_template(
        "index.html", results=results, soundcloud_url=soundcloud_url
    )


@app.route("/playlist", methods=["GET", "POST"])
def playlist():
    if not _is_authorized():
        if request.method == "POST" and request.form.get("access_code") == PLAYLIST_ADD_SECRET:
            session["playlist_authorized"] = True
        else:
            error = "Wrong access code." if request.method == "POST" else None
            return render_template("playlist.html", needs_code=True, authenticated=False, error=error)

    oauth = _get_oauth()
    token_info = oauth.validate_token(oauth.cache_handler.get_cached_token())

    if not token_info:
        return render_template("playlist.html", authenticated=False)

    if request.method != "POST" or "links" not in request.form:
        return render_template("playlist.html", authenticated=True)

    links_text = request.form.get("links", "")
    playlist_name = request.form.get("playlist_name", "").strip() or "SoundCloud Import"
    uris = _parse_spotify_links(links_text)
    if not uris:
        return render_template(
            "playlist.html", authenticated=True, error="No valid Spotify track links found."
        )

    try:
        sp = spotipy.Spotify(auth_manager=oauth)
        playlist_id = get_or_create_playlist(
            sp, playlist_name, public=False, description="Added via Setlist"
        )
        existing_uris = get_existing_track_uris(sp, playlist_id)
        new_uris = [u for u in uris if u not in existing_uris]
        if new_uris:
            add_tracks(sp, playlist_id, new_uris)
    except Exception:
        app.logger.exception("playlist add failed")
        return render_template(
            "playlist.html",
            authenticated=True,
            error="Could not add tracks to Spotify. Please try again.",
        )

    return render_template(
        "playlist.html",
        authenticated=True,
        added=len(new_uris),
        skipped=len(uris) - len(new_uris),
        playlist_name=playlist_name,
    )


@app.route("/spotify/login")
def spotify_login():
    if not _is_authorized():
        return "Forbidden", 403
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    return redirect(_get_oauth().get_authorize_url(state=state))


@app.route("/callback")
def spotify_callback():
    if not _is_authorized():
        return "Forbidden", 403
    expected_state = session.pop("oauth_state", None)
    if not expected_state or request.args.get("state") != expected_state:
        return "Invalid or missing OAuth state.", 400
    code = request.args.get("code")
    if code:
        _get_oauth().get_access_token(code, as_dict=True)
    return redirect(url_for("playlist"))


if __name__ == "__main__":
    # Port 5000 is claimed by macOS's AirPlay Receiver service, which
    # intercepts the connection instead of Flask - use a port that's free.
    app.run(debug=True, threaded=True, port=5050)
