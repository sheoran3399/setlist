from __future__ import annotations

import argparse
import sys

from config import load_config
from identify import identify_dj_set, identify_from_tracklist, identify_single_track, parse_tracklist
from recognizer import Recognition
from soundcloud_source import list_playlist_tracks
from spotify_client import (
    add_tracks,
    build_client,
    get_existing_track_uris,
    get_or_create_playlist,
    pick_best_match,
    search_candidates,
)


def resolve_uri(
    sp, recognition: Recognition | None, fallback_artist: str | None, fallback_title: str | None
) -> tuple[str | None, str | None]:
    """Turn a recognition (or raw metadata fallback) into a Spotify track URI.

    Prefers AudD's own artist/title over raw SoundCloud metadata whenever
    AudD identified something at all, even without a direct Spotify ID —
    AudD's parse is far cleaner than a SoundCloud upload title.
    """
    if recognition and recognition.spotify_id:
        return f"spotify:track:{recognition.spotify_id}", "audd"

    search_artist = recognition.artist if recognition else fallback_artist
    search_title = recognition.title if recognition else fallback_title
    if not search_title:
        return None, None

    candidates = search_candidates(sp, search_artist or "", search_title)
    match = pick_best_match(candidates, search_title, search_artist or "")
    if match:
        return match, "fallback"
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a SoundCloud playlist into a single Spotify playlist, "
        "identifying tracks via AudD."
    )
    parser.add_argument(
        "playlist_url",
        nargs="?",
        help="SoundCloud playlist URL. Defaults to config.yaml's soundcloud_playlist_url.",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    playlist_url = args.playlist_url or config.soundcloud_playlist_url
    if not playlist_url:
        parser.error(
            "No SoundCloud playlist URL given (pass it as an argument or set "
            "soundcloud_playlist_url in config.yaml)."
        )

    print(f"Fetching track list from {playlist_url} ...")
    tracks = list_playlist_tracks(playlist_url)
    print(f"Found {len(tracks)} tracks.")

    sp = build_client(
        config.spotify_client_id, config.spotify_client_secret, config.spotify_redirect_uri
    )
    playlist_id = get_or_create_playlist(
        sp,
        config.target_playlist_name,
        config.target_playlist_public,
        config.target_playlist_description,
    )
    existing_uris = get_existing_track_uris(sp, playlist_id)
    print(f"Target playlist '{config.target_playlist_name}' already has {len(existing_uris)} tracks.")

    resolved_uris: list[str] = []
    audd_matches = 0
    fallback_matches = 0
    unmatched: list[str] = []

    for i, track in enumerate(tracks, start=1):
        print(f"[{i}/{len(tracks)}] {track.title}")
        tracklist = parse_tracklist(track.description)
        is_dj_set = (track.duration_s or 0) >= config.dj_set_threshold_s

        if tracklist:
            print(f"    Tracklist found in description ({len(tracklist)} songs) — skipping audio recognition")
            candidates = identify_from_tracklist(track, tracklist)
        elif is_dj_set:
            minutes = (track.duration_s or 0) / 60
            print(f"    DJ set detected ({minutes:.1f} min) — sampling multiple points")
            candidates = identify_dj_set(track, config)
        else:
            candidates = identify_single_track(track, config)

        for label, recognition, fallback_artist, fallback_title in candidates:
            uri, method = resolve_uri(sp, recognition, fallback_artist, fallback_title)

            if method == "audd":
                audd_matches += 1
            elif method == "fallback":
                fallback_matches += 1

            if uri:
                print(f"    {label} -> matched ({method})")
                if uri not in existing_uris and uri not in resolved_uris:
                    resolved_uris.append(uri)
            else:
                print(f"    {label} -> no match")
                unmatched.append(label)

    if resolved_uris:
        print(f"Adding {len(resolved_uris)} new tracks to '{config.target_playlist_name}' ...")
        add_tracks(sp, playlist_id, resolved_uris)

    print("\nDone.")
    print(f"  Identified via AudD:      {audd_matches}")
    print(f"  Identified via fallback:  {fallback_matches}")
    print(f"  Added to playlist:        {len(resolved_uris)}")
    print(f"  Unmatched:                {len(unmatched)}")
    for title in unmatched:
        print(f"    - {title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
