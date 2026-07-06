from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    spotify_client_id: str
    spotify_client_secret: str
    spotify_redirect_uri: str
    soundcloud_playlist_url: str
    target_playlist_name: str
    target_playlist_public: bool
    target_playlist_description: str
    dj_set_threshold_s: float
    dj_set_edge_margin_s: float
    dj_set_sample_interval_s: float
    shazam_segment_seconds: int
    shazam_confirm_offset_s: float
    shazam_concurrency: int


def load_config(path: str = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text()) or {}

    return Config(
        # Optional: only main.py's Spotify playlist-building step needs these.
        # The identification-only web UI never touches Spotify's API.
        spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        spotify_client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
        spotify_redirect_uri=os.environ.get(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback"
        ),
        soundcloud_playlist_url=raw.get("soundcloud_playlist_url", ""),
        target_playlist_name=raw.get("target_playlist_name", "SoundCloud Import"),
        target_playlist_public=bool(raw.get("target_playlist_public", False)),
        target_playlist_description=raw.get("target_playlist_description", ""),
        dj_set_threshold_s=float(raw.get("dj_set_threshold_minutes", 10)) * 60,
        dj_set_edge_margin_s=float(raw.get("dj_set_edge_margin_seconds", 60)),
        dj_set_sample_interval_s=float(raw.get("dj_set_sample_interval_seconds", 240)),
        shazam_segment_seconds=int(raw.get("shazam_segment_seconds", 15)),
        shazam_confirm_offset_s=float(raw.get("shazam_confirm_offset_seconds", 7)),
        shazam_concurrency=int(raw.get("shazam_concurrency", 6)),
    )
