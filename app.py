from __future__ import annotations

from flask import Flask, render_template, request

from config import load_config
from identify import identify_track
from soundcloud_source import list_playlist_tracks

app = Flask(__name__)


def extract_track_names(soundcloud_url: str) -> list[dict]:
    """Identify every song referenced by a SoundCloud URL, no Spotify involved.

    Returns one dict per identified (or unidentified) item: {label, artist,
    title, matched}. DJ sets expand into multiple items (one per sample
    point); ordinary tracks yield exactly one.
    """
    config = load_config()
    sc_tracks = list_playlist_tracks(soundcloud_url)

    results = []
    for sc_track in sc_tracks:
        for label, recognition, fallback_artist, fallback_title in identify_track(sc_track, config):
            if recognition:
                spotify_url = (
                    f"https://open.spotify.com/track/{recognition.spotify_id}"
                    if recognition.spotify_id
                    else None
                )
                results.append(
                    {
                        "label": label,
                        "artist": recognition.artist,
                        "title": recognition.title,
                        "matched": True,
                        "spotify_url": spotify_url,
                    }
                )
            elif fallback_title:
                results.append(
                    {
                        "label": label,
                        "artist": fallback_artist or "(unknown artist)",
                        "title": fallback_title,
                        "matched": False,
                        "spotify_url": None,
                    }
                )
            else:
                results.append(
                    {
                        "label": label,
                        "artist": None,
                        "title": None,
                        "matched": False,
                        "spotify_url": None,
                    }
                )
    return results


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method != "POST":
        return render_template("index.html")

    soundcloud_url = request.form.get("soundcloud_url", "").strip()
    if not soundcloud_url:
        return render_template("index.html", error="Paste a SoundCloud URL first.")

    try:
        results = extract_track_names(soundcloud_url)
    except Exception as exc:  # noqa: BLE001 - surface any failure to the page
        return render_template("index.html", error=str(exc), soundcloud_url=soundcloud_url)

    return render_template(
        "index.html", results=results, soundcloud_url=soundcloud_url
    )


if __name__ == "__main__":
    # Port 5000 is claimed by macOS's AirPlay Receiver service, which
    # intercepts the connection instead of Flask - use a port that's free.
    app.run(debug=True, threaded=True, port=5050)
