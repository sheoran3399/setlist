from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from shazamio import Shazam


@dataclass
class ShazamMatch:
    artist: str
    title: str


async def _recognize_one(shazam: Shazam, sem: asyncio.Semaphore, path: Path) -> ShazamMatch | None:
    async with sem:
        try:
            result = await shazam.recognize(str(path))
        except Exception:
            return None

    track = result.get("track") if result else None
    if not track:
        return None
    artist = (track.get("subtitle") or "").strip()
    title = (track.get("title") or "").strip()
    if not artist or not title:
        return None
    return ShazamMatch(artist=artist, title=title)


async def _recognize_many_async(paths: list[Path], concurrency: int) -> list[ShazamMatch | None]:
    shazam = Shazam()
    sem = asyncio.Semaphore(concurrency)
    return await asyncio.gather(*(_recognize_one(shazam, sem, p) for p in paths))


def recognize_many(paths: list[Path], concurrency: int = 6) -> list[ShazamMatch | None]:
    """Recognize many audio clips against Shazam's free, unofficial API.

    Shazam has no per-request cost (unlike AudD), so dense wall-to-wall
    tiling of a DJ set is affordable — this runs requests concurrently
    (bounded by `concurrency`) to keep that dense scan fast.
    """
    return asyncio.run(_recognize_many_async(paths, concurrency))


def recognize(path: Path) -> ShazamMatch | None:
    return recognize_many([path], concurrency=1)[0]
