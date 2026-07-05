from __future__ import annotations

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yt_dlp

FLAT_OPTS = {"extract_flat": True, "quiet": True, "no_warnings": True}


@dataclass
class SoundCloudTrack:
    url: str
    title: str
    uploader: str | None
    duration_s: float | None = None


def _flat_extract(url: str) -> dict:
    with yt_dlp.YoutubeDL(FLAT_OPTS) as ydl:
        return ydl.extract_info(url, download=False)


def _resolve(url: str, _depth: int = 0) -> dict:
    """Follow indirect '_type: url' redirects until we hit real metadata.

    on.soundcloud.com share links (the ones the SoundCloud app generates)
    are handled by yt-dlp's generic extractor, which under extract_flat
    returns a bare {'_type': 'url', 'url': '<canonical soundcloud.com link>'}
    placeholder instead of resolving it. We have to follow that ourselves.
    """
    if _depth > 5:
        raise RuntimeError(f"Too many redirects resolving {url}")
    info = _flat_extract(url)
    if info.get("_type") == "url" and info.get("url"):
        return _resolve(info["url"], _depth + 1)
    return info


def list_playlist_tracks(playlist_url: str) -> list[SoundCloudTrack]:
    """Enumerate a SoundCloud playlist's tracks without downloading any audio.

    Also accepts a single-track URL (playlist_url doesn't have to actually be
    a playlist) — in that case this returns a one-item list.
    """
    info = _resolve(playlist_url)

    entries = info.get("entries")
    if entries is None:
        return [
            SoundCloudTrack(
                url=info.get("webpage_url") or playlist_url,
                title=info.get("title") or "",
                uploader=info.get("uploader"),
                duration_s=info.get("duration"),
            )
        ]

    tracks: list[SoundCloudTrack] = []
    for entry in entries:
        if not entry:
            continue
        tracks.append(
            SoundCloudTrack(
                url=entry.get("url") or entry.get("webpage_url"),
                title=entry.get("title") or "",
                uploader=entry.get("uploader"),
                duration_s=entry.get("duration"),
            )
        )
    return tracks


@contextmanager
def full_audio_file(track: SoundCloudTrack) -> Iterator[Path]:
    """Download a track's full audio, for fingerprinting purposes.

    AudD's `url` param only fetches from a handful of platforms (Instagram,
    TikTok, etc.) and plain direct-audio-file links — it does NOT fetch
    generic SoundCloud page URLs, so we have to pull the audio ourselves and
    upload clips of it as a file.

    We download the full track rather than using yt-dlp's server-side
    download_ranges: SoundCloud serves audio over HLS by default, and
    range-clipping HLS turned out to be extremely slow and produced corrupt
    output in testing. Forcing the plain progressive "http_mp3" format
    (which SoundCloud offers for virtually every track) keeps the download
    itself fast for normal-length songs.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="sc2sp_"))
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "http_mp3_1_0/bestaudio/best",
            "outtmpl": str(tmp_dir / "full.%(ext)s"),
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}
            ],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([track.url])

        full_path = tmp_dir / "full.mp3"
        if not full_path.exists():
            raise RuntimeError(f"Failed to download audio for {track.url}")
        yield full_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def extract_clip(full_path: Path, start_s: float, clip_seconds: int) -> Path:
    """Cut a clip_seconds-long clip out of full_path starting at start_s."""
    clip_path = full_path.parent / f"clip_{int(start_s)}.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start_s), "-t", str(clip_seconds),
            "-i", str(full_path),
            str(clip_path),
        ],
        check=True,
    )
    return clip_path


@contextmanager
def snippet_file(track: SoundCloudTrack, clip_seconds: int = 12) -> Iterator[Path]:
    """Download a track and yield a single short clip from it (one recognition attempt)."""
    start = 30 if (track.duration_s or 0) > 60 else 0
    with full_audio_file(track) as full_path:
        yield extract_clip(full_path, start, clip_seconds)
