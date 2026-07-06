from __future__ import annotations

import re
from typing import Iterator

import shazam_recognizer
from config import Config
from recognizer import Recognition
from soundcloud_source import SoundCloudTrack, extract_clip, full_audio_file, snippet_file

# label, recognition (always None now — kept for interface compatibility with
# resolve_uri/app.py), fallback artist/title from whatever identified the song.
Candidate = tuple[str, "Recognition | None", "str | None", "str | None"]

# Matches lines like "00:00     Artist - Title" or "01:00:21  Artist - Title",
# the tracklist format most DJs use in their SoundCloud upload descriptions.
_TRACKLIST_LINE = re.compile(
    r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s+(.+?)\s*$",
    re.MULTILINE,
)


def split_title_artist(sc_title: str, sc_uploader: str | None) -> tuple[str, str]:
    """Best-effort (title, artist) guess from raw SoundCloud metadata."""
    if " - " in sc_title:
        artist, title = sc_title.split(" - ", 1)
        return title.strip(), artist.strip()
    return sc_title.strip(), (sc_uploader or "").strip()


def parse_tracklist(description: str | None) -> list[tuple[float, str, str]]:
    """Parse a "MM:SS Artist - Title" tracklist out of a SoundCloud description.

    Many DJs list their exact track selection with timestamps in the upload
    description. When present, this is free and 100% accurate — a bonus for
    the uploads that have it, not a general fix for the ones that don't.
    Requires at least 3 matched lines so a description that just happens to
    mention a time once doesn't misfire.
    """
    if not description:
        return []

    entries = []
    for match in _TRACKLIST_LINE.finditer(description):
        hours, minutes, seconds, rest = match.groups()
        if " - " not in rest:
            continue
        time_s = int(minutes) * 60 + int(seconds) + (int(hours) * 3600 if hours else 0)
        artist, title = rest.split(" - ", 1)
        entries.append((float(time_s), artist.strip(), title.strip()))

    return entries if len(entries) >= 3 else []


def identify_single_track(track: SoundCloudTrack, config: Config) -> Iterator[Candidate]:
    with snippet_file(track) as clip_path:
        match = shazam_recognizer.recognize(clip_path)
    if match:
        yield track.title, None, match.artist, match.title
        return
    guess_title, guess_artist = split_title_artist(track.title, track.uploader)
    yield track.title, None, guess_artist, guess_title


def _agree(matches: list["shazam_recognizer.ShazamMatch | None"]) -> tuple[str, str] | None:
    """Return (artist, title) only if at least two of the given matches agree.

    A single clip matching a song isn't trusted on its own — Shazam (like any
    fingerprinting service) occasionally returns a confident-looking wrong
    match. Requiring two independent nearby clips to agree filters that out:
    a real song shows up consistently, a spurious match doesn't repeat.
    """
    valid = [m for m in matches if m]
    for i, a in enumerate(valid):
        key_a = (a.artist.strip().lower(), a.title.strip().lower())
        for b in valid[i + 1 :]:
            key_b = (b.artist.strip().lower(), b.title.strip().lower())
            if key_a == key_b:
                return a.artist, a.title
    return None


def identify_dj_set(track: SoundCloudTrack, config: Config) -> Iterator[Candidate]:
    """Sample spaced-out points across a long mix, confirming each with Shazam.

    A DJ set is one continuous recording, not one song, so a single call only
    ever identifies whatever's playing at one instant. Shazam's (unofficial,
    free) API rate-limits hard under sustained volume, so unlike a paid
    per-request service we can't afford to scan the whole mix densely —
    instead we keep the same sparse interval as before, but take two nearby
    clips per point and only accept a match when both agree (see _agree),
    which catches single-clip false positives without needing to scan
    everything.
    """
    duration = track.duration_s or 0
    start = config.dj_set_edge_margin_s
    end = duration - config.dj_set_edge_margin_s
    seg = config.shazam_segment_seconds
    offset = config.shazam_confirm_offset_s

    sample_points = []
    t = start
    while t < end:
        sample_points.append(t)
        t += config.dj_set_sample_interval_s
    if not sample_points:
        sample_points = [duration / 2]

    with full_audio_file(track) as full_path:
        clip_paths: list = []
        point_slices: list[tuple[float, int, int]] = []
        for t in sample_points:
            idx_start = len(clip_paths)
            for sub_t in (t, t + offset):
                if sub_t + seg <= end:
                    clip_paths.append(extract_clip(full_path, sub_t, seg))
            point_slices.append((t, idx_start, len(clip_paths)))

        matches = shazam_recognizer.recognize_many(clip_paths, concurrency=config.shazam_concurrency)

    for t, idx_start, idx_end in point_slices:
        confirmed = _agree(matches[idx_start:idx_end])
        minutes, seconds = divmod(int(t), 60)
        label = f"{track.title} @ {minutes}:{seconds:02d}"
        if confirmed:
            artist, title = confirmed
            yield label, None, artist, title
        else:
            yield label, None, None, None


def identify_from_tracklist(
    track: SoundCloudTrack, tracklist: list[tuple[float, str, str]]
) -> Iterator[Candidate]:
    """Yield candidates straight from a parsed description tracklist — no audio involved."""
    for time_s, artist, title in tracklist:
        minutes, seconds = divmod(int(time_s), 60)
        label = f"{track.title} @ {minutes}:{seconds:02d}"
        yield label, None, artist, title


def identify_track(track: SoundCloudTrack, config: Config) -> Iterator[Candidate]:
    """Dispatch to tracklist, single-track, or DJ-set identification."""
    tracklist = parse_tracklist(track.description)
    if tracklist:
        yield from identify_from_tracklist(track, tracklist)
    elif (track.duration_s or 0) >= config.dj_set_threshold_s:
        yield from identify_dj_set(track, config)
    else:
        yield from identify_single_track(track, config)
