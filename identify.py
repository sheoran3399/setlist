from __future__ import annotations

from typing import Iterator

from config import Config
from recognizer import Recognition, recognize
from soundcloud_source import SoundCloudTrack, extract_clip, full_audio_file, snippet_file

# label, recognition (None if unidentified), fallback artist/title guessed
# from raw SoundCloud metadata (only meaningful when recognition is None).
Candidate = tuple[str, "Recognition | None", "str | None", "str | None"]


def split_title_artist(sc_title: str, sc_uploader: str | None) -> tuple[str, str]:
    """Best-effort (title, artist) guess from raw SoundCloud metadata."""
    if " - " in sc_title:
        artist, title = sc_title.split(" - ", 1)
        return title.strip(), artist.strip()
    return sc_title.strip(), (sc_uploader or "").strip()


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
            minutes, seconds = divmod(int(t), 60)
            label = f"{track.title} @ {minutes}:{seconds:02d}"
            yield label, recognition, None, None


def identify_track(track: SoundCloudTrack, config: Config) -> Iterator[Candidate]:
    """Dispatch to single-track or DJ-set identification based on duration."""
    if (track.duration_s or 0) >= config.dj_set_threshold_s:
        yield from identify_dj_set(track, config)
    else:
        yield from identify_single_track(track, config)
