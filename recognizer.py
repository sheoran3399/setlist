from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import requests

AUDD_ENDPOINT = "https://api.audd.io/"


@dataclass
class Recognition:
    artist: str
    title: str
    spotify_id: str | None  # Present when AudD itself resolved a Spotify match.


def recognize(api_token: str, audio_clip_path: Path) -> Recognition | None:
    """Ask AudD to identify a track from a local audio clip.

    AudD's `url` param only fetches from a handful of specific platforms and
    direct audio-file links — it does not fetch generic SoundCloud page URLs
    — so the caller downloads a short clip first (see
    soundcloud_source.snippet_file) and we upload it as a file instead.

    Passing return=spotify makes AudD do the Spotify lookup for us and
    include the matched track's Spotify ID in the response, so a confident
    AudD match skips our own Spotify search entirely.
    """
    with open(audio_clip_path, "rb") as audio_file:
        response = requests.post(
            AUDD_ENDPOINT,
            data={"api_token": api_token, "return": "spotify"},
            files={"file": audio_file},
            timeout=60,
        )
    response.raise_for_status()
    payload = response.json()

    if payload.get("status") != "success" or not payload.get("result"):
        return None

    result = payload["result"]
    spotify = result.get("spotify") or {}
    return Recognition(
        artist=result.get("artist", ""),
        title=result.get("title", ""),
        spotify_id=spotify.get("id"),
    )
