# Setlist

Turn a SoundCloud track — or a full DJ set — into a list of identified songs with direct Spotify links, and optionally build them straight into a Spotify playlist.

SoundCloud uploads (especially DJ sets and mixes) often have messy or missing metadata. This tool identifies the actual songs by audio fingerprinting via [AudD](https://audd.io), not by trusting the upload title. Long recordings (10+ minutes) are treated as DJ sets: instead of one recognition attempt, the audio is sampled at multiple points across the mix and each identified song is returned separately.

## What's included

- **Web UI** (`app.py`) — paste a SoundCloud URL, get back an artist/title list with Spotify links. No Spotify account needed for this part.
- **CLI** (`main.py`) — same identification pipeline, but pushes every result into one Spotify playlist in your account (requires Spotify auth).

## How it works

1. [yt-dlp](https://github.com/yt-dlp/yt-dlp) lists the track(s) in a SoundCloud URL (playlist or single track) without downloading audio.
2. For a normal-length track, a short clip is downloaded and sent to AudD for recognition.
3. For anything at or above `dj_set_threshold_minutes` (default 10), the full track is downloaded once and sampled at `dj_set_sample_interval_seconds` intervals (default every 4 minutes) — each sample is identified independently.
4. When AudD resolves a Spotify match directly (via its `return=spotify` option), that Spotify track ID is used as-is — no separate Spotify search needed.
5. When AudD identifies a song but has no direct Spotify match, a fallback Spotify text search finds the best candidate (`spotify_client.py::pick_best_match`, using fuzzy title/artist similarity).
6. (CLI only) All resolved tracks are added to one target Spotify playlist, deduplicated against what's already in it.

## Setup

### Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) — `brew install ffmpeg` on macOS
- An [AudD](https://audd.io) API token
- A [Spotify Developer app](https://developer.spotify.com/dashboard) — only needed for the CLI's playlist-building step, not the web UI

### Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Configure secrets

Copy `.env.example` to `.env` and fill in:

```
AUDD_API_TOKEN=your-audd-token
SPOTIFY_CLIENT_ID=your-spotify-client-id
SPOTIFY_CLIENT_SECRET=your-spotify-client-secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8080/callback
```

To create the Spotify app: go to the [developer dashboard](https://developer.spotify.com/dashboard) → **Create app** → set the redirect URI to exactly `http://127.0.0.1:8080/callback` (Spotify requires a loopback IP, not `localhost`) → check **Web API** → save, then copy the Client ID and Secret from the app's Settings page.

### Configure run settings

Non-secret settings live in `config.yaml`: target playlist name/visibility, DJ set detection threshold, and sampling density. Defaults are sensible; tune `dj_set_sample_interval_seconds` down if a mix has short back-to-back songs (denser sampling costs more AudD requests).

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

## Known limitation: Spotify Premium

As of Spotify's 2024–2025 API policy changes, several Web API endpoints — including fetching your profile and creating playlists — require the account that **owns the developer app** to have an active Premium subscription. This doesn't need to be the account you're identifying tracks *for*; a Premium account can own the app and add other accounts as allowed users (Settings → User Management) while apps are in Development Mode. The web UI's identification flow is unaffected, since it never calls the Spotify API.

## Project layout

```
soundcloud_source.py   SoundCloud track listing + audio download (yt-dlp)
recognizer.py          AudD recognition (audio clip -> artist/title/Spotify ID)
identify.py            Single-track vs DJ-set-sampling dispatch, shared by CLI and web UI
spotify_client.py      Spotify OAuth, playlist creation, fallback search + matching
config.py              Loads .env (secrets) + config.yaml (run settings)
main.py                CLI: identify -> build Spotify playlist
app.py                 Web UI: identify -> display results, no Spotify writes
```
