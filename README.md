# Setlist

**Live: https://setlist-production-a054.up.railway.app**

Turn a SoundCloud track — or a full DJ set — into a list of identified songs with Spotify links, and optionally build them straight into a Spotify playlist.

SoundCloud uploads (especially DJ sets and mixes) often have messy or missing metadata. This tool identifies the actual songs by audio fingerprinting via [Shazam](https://www.shazam.com) (via the free, unofficial [shazamio](https://github.com/dotX12/ShazamIO) library), not by trusting the upload title. Long recordings (10+ minutes) are treated as DJ sets: instead of one recognition attempt, the mix is sampled at multiple spaced-out points and each identified song is returned separately.

## What's included

- **Web UI** (`app.py`) — paste a SoundCloud URL, get back an artist/title list with Spotify search links and genre/mood tags. No Spotify account needed for this part.
- **CLI** (`main.py`) — same identification pipeline, but pushes every result into one Spotify playlist in your account (requires Spotify auth).

## How it works

1. [yt-dlp](https://github.com/yt-dlp/yt-dlp) lists the track(s) in a SoundCloud URL (playlist or single track) without downloading audio.
2. If the uploader included a timestamped tracklist in the description (`MM:SS Artist - Title`), it's parsed directly — 100% accurate, no audio recognition needed. This only helps when it's present; most uploads don't have one.
3. Otherwise, for a normal-length track, a short clip is downloaded and sent to Shazam for recognition.
4. For anything at or above `dj_set_threshold_minutes` (default 10), the full track is downloaded once and sampled at `dj_set_sample_interval_seconds` intervals (default every 4 minutes). At each point, **two** nearby clips (`shazam_confirm_offset_seconds` apart) are both sent to Shazam — a song is only reported if both agree, which filters out the occasional confident-but-wrong match any fingerprinting service can produce. Shazam's unofficial API rate-limits hard under heavy volume, which is why sampling stays sparse rather than scanning the whole set densely.
5. Since Shazam doesn't resolve a specific Spotify track ID (unlike some paid alternatives), the web UI links to a Spotify **search** results page for the identified artist/title rather than a confirmed track — this needs no Spotify API call or credentials.
6. Genre and mood tags are generated per track by asking Claude (Haiku 4.5) to classify from the artist/title alone (`claude_tagger.py`).
7. (CLI only) Each identified track is resolved to a specific Spotify track ID via a real Spotify search (`spotify_client.py::pick_best_match`), and added to one target playlist, deduplicated against what's already in it.

## Setup

### Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg` on macOS
- An [Anthropic API key](https://console.anthropic.com/settings/keys) — for genre/mood tagging
- A [Spotify Developer app](https://developer.spotify.com/dashboard) — only needed for the CLI's playlist-building step, not the web UI

### Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Configure secrets

Copy `.env.example` to `.env` and fill in:

```
ANTHROPIC_API_KEY=your-anthropic-key
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

To create the Spotify app: go to the [developer dashboard](https://developer.spotify.com/dashboard) → **Create app** → set the redirect URI to exactly `http://127.0.0.1:8080/callback` (Spotify requires a loopback IP, not `localhost`) → check **Web API** → save, then copy the Client ID and Secret from the app's Settings page.

### Configure run settings

Non-secret settings live in `config.yaml`: target playlist name/visibility, DJ set detection threshold, and Shazam sampling density (`shazam_concurrency`, `shazam_segment_seconds`, `shazam_confirm_offset_seconds`).

## Running it

**Web UI** (identification only, no Spotify account required):

```bash
.venv/bin/python app.py
```

Open http://127.0.0.1:5050 (not 5000 — macOS's AirPlay Receiver claims that port).

**CLI** (identifies tracks *and* adds them to a Spotify playlist):

```bash
.venv/bin/python main.py "https://soundcloud.com/..."
```

Omit the URL to use `soundcloud_playlist_url` from `config.yaml` instead. The first run opens a browser for Spotify login/consent.

## Deployment

The web UI is deployed on [Railway](https://railway.app) via the included `Dockerfile` (a plain Python buildpack won't work — `ffmpeg` has to be installed at the OS level). Only `ANTHROPIC_API_KEY` is set as a host env var; the deployed instance never touches Spotify credentials since the web UI doesn't call the Spotify API at all.

To redeploy from scratch:

```bash
railway login
railway init
railway variables --set "ANTHROPIC_API_KEY=..."
railway up
railway domain
```

## Known limitation: Spotify Premium

As of Spotify's 2024–2025 API policy changes, several Web API endpoints — including fetching your profile and creating playlists — require the account that **owns the developer app** to have an active Premium subscription. This doesn't need to be the account you're identifying tracks *for*; a Premium account can own the app and add other accounts as allowed users (Settings → User Management) while apps are in Development Mode. The web UI's identification flow is unaffected, since it never calls the Spotify API.

## Project layout

```
soundcloud_source.py   SoundCloud track listing + audio download (yt-dlp)
shazam_recognizer.py    Shazam recognition (audio clip -> artist/title), concurrent batch support
recognizer.py           AudD recognition -- no longer used, kept for reference
identify.py             Tracklist / single-track / DJ-set dispatch, shared by CLI and web UI
claude_tagger.py        Genre/mood classification from artist/title via Claude Haiku 4.5
spotify_client.py       Spotify OAuth, playlist creation, fallback search + matching
config.py               Loads .env (secrets) + config.yaml (run settings)
main.py                 CLI: identify -> build Spotify playlist
app.py                  Web UI: identify -> display results, no Spotify writes
```
