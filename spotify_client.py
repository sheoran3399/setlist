from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = "playlist-modify-public playlist-modify-private"


@dataclass
class SearchCandidate:
    uri: str
    name: str
    artists: list[str]
    duration_ms: int


def get_oauth(
    client_id: str, client_secret: str, redirect_uri: str, cache_path: str = ".spotify_token_cache"
) -> SpotifyOAuth:
    """Raw OAuth manager, for callers that need to drive the auth code exchange
    themselves (a deployed web app can't use spotipy's local-browser/localhost-
    server convenience flow — that only works for a script running on the same
    machine as the browser). CLI usage still goes through this same cache file,
    so authenticating once from either surface covers both.
    """
    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_path=cache_path,
    )


def build_client(client_id: str, client_secret: str, redirect_uri: str) -> spotipy.Spotify:
    return spotipy.Spotify(auth_manager=get_oauth(client_id, client_secret, redirect_uri))


def get_or_create_playlist(
    sp: spotipy.Spotify, name: str, public: bool, description: str
) -> str:
    user_id = sp.me()["id"]

    offset = 0
    while True:
        page = sp.current_user_playlists(limit=50, offset=offset)
        for playlist in page["items"]:
            if playlist["name"] == name:
                return playlist["id"]
        if not page["next"]:
            break
        offset += 50

    playlist = sp.user_playlist_create(
        user_id, name, public=public, description=description
    )
    return playlist["id"]


def get_existing_track_uris(sp: spotipy.Spotify, playlist_id: str) -> set[str]:
    uris: set[str] = set()
    offset = 0
    while True:
        page = sp.playlist_items(
            playlist_id, fields="items.track.uri,next", offset=offset, limit=100
        )
        for item in page["items"]:
            track = item.get("track")
            if track and track.get("uri"):
                uris.add(track["uri"])
        if not page["next"]:
            break
        offset += 100
    return uris


def search_candidates(sp: spotipy.Spotify, artist: str, title: str, limit: int = 5) -> list[SearchCandidate]:
    query = f"track:{title} artist:{artist}" if artist else title
    results = sp.search(q=query, type="track", limit=limit)
    items = results.get("tracks", {}).get("items", [])
    return [
        SearchCandidate(
            uri=item["uri"],
            name=item["name"],
            artists=[a["name"] for a in item["artists"]],
            duration_ms=item["duration_ms"],
        )
        for item in items
    ]


MATCH_THRESHOLD = 0.6  # Tune this: higher = fewer wrong adds, more skipped tracks.


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text)  # drop "(official video)", "(remix)", etc.
    text = re.sub(r"\bfeat\.?\b.*", "", text)  # drop "feat. X" tails
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def pick_best_match(
    candidates: list[SearchCandidate], target_title: str, target_artist: str
) -> str | None:
    """Choose which Spotify search result (if any) is the real match.

    This only runs for tracks AudD couldn't confidently identify, so we're
    matching on noisy SoundCloud metadata (target_title/target_artist) against
    a handful of Spotify search candidates. There's no single right answer:
    - Exact (case-insensitive) title+artist string equality is strict and
      avoids wrong adds, but misses remasters/"feat." variations.
    - Fuzzy string similarity (used below, via difflib.SequenceMatcher) catches
      more real matches but risks a false positive on a similarly-named
      different song.
    - Just taking candidates[0] trusts Spotify's own search ranking.

    Default heuristic: normalize (strip casing/punctuation/parentheticals),
    score title and artist similarity separately, weight title higher since
    it's the stronger signal, and require a combined score above
    MATCH_THRESHOLD. Revisit this if you see wrong tracks slipping in
    (raise the threshold) or too many real matches skipped (lower it, or
    swap in a library like rapidfuzz for better fuzzy matching).
    """
    target_title_n = _normalize(target_title)
    target_artist_n = _normalize(target_artist)

    best_uri: str | None = None
    best_score = 0.0
    for candidate in candidates:
        title_score = SequenceMatcher(None, target_title_n, _normalize(candidate.name)).ratio()
        artist_score = max(
            (SequenceMatcher(None, target_artist_n, _normalize(a)).ratio() for a in candidate.artists),
            default=0.0,
        )
        score = title_score * 0.7 + artist_score * 0.3

        if score > best_score:
            best_score = score
            best_uri = candidate.uri

    return best_uri if best_score >= MATCH_THRESHOLD else None


def add_tracks(sp: spotipy.Spotify, playlist_id: str, track_uris: list[str]) -> None:
    for i in range(0, len(track_uris), 100):
        sp.playlist_add_items(playlist_id, track_uris[i : i + 100])
