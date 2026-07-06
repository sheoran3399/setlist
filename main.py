from __future__ import annotations

import argparse
import sys

from config import load_config
from identify import identify_dj_set, identify_from_tracklist, identify_single_track, parse_tracklist
from soundcloud_source import list_playlist_tracks
from spotify_client import (
    add_tracks,
    build_client,
    get_existing_track_uris,
    get_or_create_playlist,
    pick_best_match,
    search_candidates,
)


def resolve_uri(sp, artist: str | None, title: str | None) -> str | None:
    """Search Spotify for the identified artist/title and return the best-match URI."""
    if not title:
        return None
    candidates = search_candidates(sp, artist or "", title)
    return pick_best_match(candidates, title, artist or "")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a SoundCloud playlist into a single Spotify playlist, "
        "identifying tracks via Shazam."
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
            print(f"    DJ set detected ({minutes:.1f} min) — scanning with Shazam")
            candidates = identify_dj_set(track, config)
        else:
            candidates = identify_single_track(track, config)

        for label, _recognition, artist, title in candidates:
            uri = resolve_uri(sp, artist, title)

            if uri:
                print(f"    {label} -> matched: {artist} - {title}")
                if uri not in existing_uris and uri not in resolved_uris:
                    resolved_uris.append(uri)
            else:
                print(f"    {label} -> no match")
                unmatched.append(label)

    if resolved_uris:
        print(f"Adding {len(resolved_uris)} new tracks to '{config.target_playlist_name}' ...")
        add_tracks(sp, playlist_id, resolved_uris)

    print("\nDone.")
    print(f"  Added to playlist: {len(resolved_uris)}")
    print(f"  Unmatched:         {len(unmatched)}")
    for title in unmatched:
        print(f"    - {title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
