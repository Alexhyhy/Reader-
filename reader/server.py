"""
朗读者 (Reader) — English news reader for listening & dictation practice.
Extracts article content from URLs and reads it aloud with neural TTS.
"""

import asyncio
import json
import os
import re
import tempfile
import time
import uuid

import edge_tts
import trafilatura
from flask import Flask, jsonify, render_template, request, send_file, url_for

app = Flask(__name__)

_audio_store: dict[str, dict] = {}
_AUDIO_MAX_AGE = 3600

VOICES = [
    {"id": "en-US-AriaNeural", "label": "Aria (US — Female, Professional)", "gender": "female"},
    {"id": "en-US-JennyNeural", "label": "Jenny (US — Female, Warm)", "gender": "female"},
    {"id": "en-US-GuyNeural", "label": "Guy (US — Male, Natural)", "gender": "male"},
    {"id": "en-US-ChristopherNeural", "label": "Christopher (US — Male, Authoritative)", "gender": "male"},
    {"id": "en-GB-SoniaNeural", "label": "Sonia (UK — Female)", "gender": "female"},
    {"id": "en-GB-RyanNeural", "label": "Ryan (UK — Male)", "gender": "male"},
]

SPEEDS = [
    {"value": "-20%", "label": "0.8x (Slow)"},
    {"value": "-10%", "label": "0.9x"},
    {"value": "+0%", "label": "1.0x (Normal)"},
    {"value": "+10%", "label": "1.1x"},
    {"value": "+20%", "label": "1.2x (Fast)"},
]


def _cleanup_old_audio():
    now = time.time()
    stale = [aid for aid, data in _audio_store.items() if now - data["created"] > _AUDIO_MAX_AGE]
    for aid in stale:
        try:
            os.unlink(_audio_store[aid]["path"])
        except OSError:
            pass
        del _audio_store[aid]


def _split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    merged = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if merged and len(merged[-1]) < 30:
            merged[-1] = merged[-1] + " " + s
        else:
            merged.append(s)
    return merged


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/voices")
def get_voices():
    return jsonify({"voices": VOICES, "speeds": SPEEDS})


@app.route("/api/extract", methods=["POST"])
def extract():
    data = request.get_json()
    url = data.get("url", "").strip()

    if url:
        # URL mode: fetch and extract
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return jsonify({"error": "Could not fetch the page. The site may block automated access."}), 400

            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            if not text:
                return jsonify({"error": "No article content found on this page."}), 400

            meta_raw = trafilatura.extract(downloaded, output_format="json", with_metadata=True)
            title = "Untitled"
            if meta_raw:
                try:
                    meta = json.loads(meta_raw)
                    title = meta.get("title", "Untitled")
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            return jsonify({"error": f"Extraction failed: {str(e)}"}), 500
    else:
        # Paste mode: use provided text directly
        text = data.get("text", "").strip()
        title = data.get("title", "").strip() or "Pasted Text"
        if not text:
            return jsonify({"error": "No URL or text provided. Paste a news article or enter a URL."}), 400

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    sentences = _split_sentences(text)

    return jsonify({
        "title": title,
        "text": text,
        "paragraphs": paragraphs,
        "sentences": sentences,
        "word_count": len(text.split()),
        "url": url or "(pasted text)",
    })


@app.route("/api/tts", methods=["POST"])
def generate_tts():
    data = request.get_json()
    text = data.get("text", "").strip()
    voice = data.get("voice", "en-US-AriaNeural")
    rate = data.get("rate", "+0%")

    if not text:
        return jsonify({"error": "No text provided"}), 400
    if len(text) > 10000:
        return jsonify({"error": "Text too long (max 10,000 characters)"}), 400

    try:
        result = asyncio.run(_do_tts(text, voice, rate))
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"TTS generation failed: {str(e)}"}), 500


async def _do_tts(text: str, voice: str, rate: str) -> dict:
    _cleanup_old_audio()

    audio_id = uuid.uuid4().hex[:12]
    tmpdir = tempfile.gettempdir()
    audio_path = os.path.join(tmpdir, f"reader_{audio_id}.mp3")

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)

    # Stream audio to file and capture word-boundary data for sentence cues

    submaker = edge_tts.SubMaker()
    with open(audio_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] in ("SentenceBoundary", "WordBoundary"):
                submaker.feed(chunk)

    # Build sentence-level cues from SubMaker output (Subtitle named tuples)
    sentence_cues = []
    for cue in submaker.cues:
        start_ms = cue.start.total_seconds() * 1000
        end_ms = cue.end.total_seconds() * 1000
        sentence_cues.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": cue.content,
        })
    sentences = [cue.content for cue in submaker.cues]
    _audio_store[audio_id] = {
        "path": audio_path,
        "cues": sentence_cues,
        "created": time.time(),
    }

    return {
        "audio_id": audio_id,
        "audio_url": url_for("serve_audio", audio_id=audio_id),
        "cues": sentence_cues,
        "sentences": sentences,
    }


def _align_cues_to_sentences(cues: list[dict], sentences: list[str]) -> list[dict]:
    if not cues:
        total_chars = sum(len(s) for s in sentences)
        result = []
        elapsed = 0.0
        for s in sentences:
            dur = (len(s) / total_chars) * 30000 if total_chars > 0 else 2000
            result.append({"start_ms": elapsed, "end_ms": elapsed + dur, "text": s})
            elapsed += dur
        return result

    result = []
    word_idx = 0
    for sent in sentences:
        sent_words = sent.lower().split()
        if not sent_words:
            continue

        start_ms = None
        end_ms = None
        matched = 0

        while word_idx < len(cues) and matched < len(sent_words):
            cue_word = cues[word_idx]["text"].strip().lower()
            sent_word = sent_words[matched].strip().lower()

            if cue_word == sent_word or sent_word.startswith(cue_word) or cue_word.startswith(sent_word):
                if start_ms is None:
                    start_ms = cues[word_idx]["start_ms"]
                end_ms = cues[word_idx]["end_ms"]
                matched += 1
                word_idx += 1
            else:
                if re.match(r"^[^\w]+$", cue_word):
                    word_idx += 1
                else:
                    word_idx += 1

        if start_ms is not None:
            result.append({"start_ms": start_ms, "end_ms": end_ms or start_ms + 1000, "text": sent})
        else:
            prev_end = result[-1]["end_ms"] if result else 0
            result.append({"start_ms": prev_end, "end_ms": prev_end + 2000, "text": sent})

    return result


@app.route("/api/audio/<audio_id>")
def serve_audio(audio_id):
    data = _audio_store.get(audio_id)
    if not data:
        return jsonify({"error": "Audio not found or expired"}), 404

    return send_file(
        data["path"],
        mimetype="audio/mpeg",
        as_attachment=False,
        download_name=f"reader_{audio_id}.mp3",
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
