from __future__ import annotations

import re
from typing import Iterator

from config import Config
from recognizer import Recognition, recognize
from soundcloud_source import SoundCloudTrack, extract_clip, full_audio_file, snippet_file

# label, recognition (None if unidentified), fallback artist/title guessed
# from raw SoundCloud metadata (only meaningful when recognition is None).
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
    description. When present, this is free and 100% accurate — unlike audio
    fingerprinting, which has a real accuracy ceiling on mixed/electronic
    content (no recognition service exceeds ~75% even on clean house/techno
    tracks, let alone live-mixed ones). Requires at least 3 matched lines so
    a description that just happens to mention a time once doesn't misfire.
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
        recognition = recognize(config.audd_api_token, clip_path)
    guess_title, guess_artist = split_title_artist(track.title, track.uploader)
    yield track.title, recognition, guess_artist, guess_title


def identify_dj_set(track: SoundCloudTrack, config: Config) -> Iterator[Candidate]:
    """Sample multiple points across a long mix and identify each song separately.

    A DJ set is one continuous recording, not one song, so a single AudD
    call only ever identifies whatever's playing at one instant. We sample
    every dj_set_sample_interval_s across the set instead; each sample either
    lands mid-song (identifiable) or during a blend/transition (often no
    match, which we report as a gap rather than guessing).
    """
    duration = track.duration_s or 0
    start = config.dj_set_edge_margin_s
    end = duration - config.dj_set_edge_margin_s

    sample_points = []
    t = start
    while t < end:
        sample_points.append(t)
        t += config.dj_set_sample_interval_s
    if not sample_points:
        sample_points = [duration / 2]

    with full_audio_file(track) as full_path:
        for t in sample_points:
            clip_path = extract_clip(full_path, t, config.dj_set_sample_clip_seconds)
            recognition = recognize(config.audd_api_token, clip_path)

            # A miss is often just landing mid-transition, not an unrecognizable
            # song — nudge forward once and retry before giving up on this point.
            if not recognition:
                retry_t = t + config.dj_set_retry_offset_s
                if retry_t + config.dj_set_sample_clip_seconds < end:
                    retry_clip = extract_clip(full_path, retry_t, config.dj_set_sample_clip_seconds)
                    recognition = recognize(config.audd_api_token, retry_clip)

            minutes, seconds = divmod(int(t), 60)
            label = f"{track.title} @ {minutes}:{seconds:02d}"
            yield label, recognition, None, None


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
