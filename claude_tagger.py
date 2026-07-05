from __future__ import annotations

import anthropic
from pydantic import BaseModel

MODEL = "claude-haiku-4-5"

_client: anthropic.Anthropic | None = None


class GenreMood(BaseModel):
    genre: str
    mood: str


def _get_client(api_key: str) -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def classify(api_key: str, artist: str, title: str) -> GenreMood | None:
    """Ask Claude for a song's genre and mood from just its artist/title.

    There's no audio involved here — this relies entirely on Claude's own
    knowledge of the track, so accuracy depends on how well-known the song
    is. Returns None on any failure (unknown track, API error) rather than
    guessing, since a wrong tag is worse than a missing one.
    """
    client = _get_client(api_key)
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=100,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f'Song: "{title}" by {artist}.\n\n'
                        "Give its primary music genre (1-3 words, e.g. 'deep house', "
                        "'hard techno') and overall mood (1-2 words, e.g. 'energetic', "
                        "'melancholic'). Lowercase, no punctuation. If you don't "
                        "recognize this specific track, make your best guess from "
                        "the artist and title alone."
                    ),
                }
            ],
            output_format=GenreMood,
        )
        return response.parsed_output
    except Exception:
        return None
