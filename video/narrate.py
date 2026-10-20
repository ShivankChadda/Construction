"""Voice every narration line with ElevenLabs and write a manifest of durations and character times.

    python3 video/narrate.py              # all lines (cached lines cost nothing)
    python3 video/narrate.py e9 a11       # only these
    SEED_e9=2 python3 video/narrate.py e9 # another take of one line

Voice KWuQEGxZQtpWhRutt6g6 (eleven_multilingual_v2): the user's choice for Hinglish (youtube repo, film 29,
15 Oct 2026). Each line is asked on its own (no previous/next context: with context a take can stop mid-vowel and
run on into the next line's text, film 29 round 7) at one speed for the whole film. Credits are the user's money:
the cache in video/build/el_cache/ keys on the text, voice and settings.

Writes video/build/narration/<id>.wav (44.1 kHz mono) and video/build/narration/manifest.json:
{id: {dur, start: [time of each character of the line], edge_db, sps}}.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from script import LINES  # noqa: E402

CACHE = HERE / "build" / "el_cache"
OUT = HERE / "build" / "narration"
VOICE = "KWuQEGxZQtpWhRutt6g6"
MODEL = "eleven_multilingual_v2"
SPEED = float(os.environ.get("EL_SPEED", "1.0"))
SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True, "speed": SPEED}
SR = 44100
LEAD = 0.04
# lines taken again because the first take was heard wrong (seed of the take that passed the speech check)
SEEDS = {"e7": 2}   # take 0: "ऑल रिसीव्ड" heard as "ऑन रिसीव्ड"


def request(text: str, seed: int | None) -> dict:
    body = {"text": text, "model_id": MODEL, "voice_settings": SETTINGS}
    if seed is not None:
        body["seed"] = seed
    key = hashlib.sha1(json.dumps([VOICE, body], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/with-timestamps"
                                 f"?output_format=mp3_44100_128", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d))
    return d


def decode(mp3: bytes) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(SR),
                        "pipe:1"], input=mp3, capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float32).copy()


def syllables(text: str) -> int:
    """Spoken Hindi syllables: one per vowel sound (independent vowel, or consonant not killed by a virama and
    not a schwa-deleted word-final consonant). Close enough to compare lines with each other (L256)."""
    n = 0
    for w in re.findall(r"[ऀ-ॿ]+", text):
        cons = re.findall(r"[क-हक़-य़](?![्])", w)
        n += max(1, len(re.findall(r"[अ-औ]", w)) + len(cons) - (1 if re.search(r"[क-ह]$", w) and len(w) > 2 else 0))
    return n


def voice_line(lid: str, text: str) -> dict:
    seed = int(os.environ[f"SEED_{lid}"]) if f"SEED_{lid}" in os.environ else SEEDS.get(lid)
    d = request(text, seed)
    a = decode(base64.b64decode(d["audio_base64"]))
    al = d["alignment"] if "".join(d["alignment"]["characters"]) == text else (d.get("normalized_alignment") or d["alignment"])
    st, en = al["character_start_times_seconds"], al["character_end_times_seconds"]
    t0 = max(0.0, st[0] - LEAD)
    win = int(0.02 * SR)
    env = np.convolve(np.abs(a), np.ones(win) / win, mode="same")
    loud = np.nonzero(env > 10 ** (-38 / 20))[0]
    t1 = min(len(a) / SR, (loud[-1] / SR if len(loud) else en[-1]) + 0.15)
    a = a[int(t0 * SR):int(t1 * SR)].copy()
    tail = a[-int(0.05 * SR):]
    edge_db = 20 * np.log10(np.sqrt(np.mean(tail ** 2)) + 1e-9)
    f = int(0.025 * SR)
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, f))
    a[:f] *= ramp
    a[-f:] *= ramp[::-1]
    rel = [x - t0 for x in st]
    if len(rel) != len(text):  # the API normalised the text: map by position
        rel = [rel[min(len(rel) - 1, round(k * (len(rel) - 1) / max(len(text) - 1, 1)))] for k in range(len(text))]
    OUT.mkdir(parents=True, exist_ok=True)
    sf.write(OUT / f"{lid}.wav", a, SR)
    # speech time without pauses longer than 0.25 s, for the syllable rate
    voiced = env[int(t0 * SR):int(t1 * SR)] > 10 ** (-40 / 20)
    speech = voiced.sum() / SR
    return {"dur": round(len(a) / SR, 3), "start": [round(x, 3) for x in rel], "edge_db": round(float(edge_db), 1),
            "sps": round(syllables(text) / max(speech, 0.1), 2), "seed": seed, "text": text}


def main(only: list[str]) -> None:
    man_path = OUT / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    for _, lid, hi, _ in LINES:
        if only and lid not in only:
            continue
        man[lid] = voice_line(lid, hi)
        m = man[lid]
        print(f"{lid:4} {m['dur']:6.2f} s  {m['sps']:4.2f} syl/s  tail {m['edge_db']:6.1f} dB")
    ids = [lid for _, lid, _, _ in LINES]
    man = {k: man[k] for k in ids if k in man}
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=0))
    total = sum(m["dur"] for m in man.values())
    rates = sorted(m["sps"] for m in man.values())
    med = rates[len(rates) // 2]
    print(f"{len(man)} lines, {total / 60:.1f} min of speech; median {med} syl/s")
    for k, m in man.items():
        if abs(m["sps"] - med) / med > 0.08:
            print(f"  rate: {k} {m['sps']} syl/s is {100 * (m['sps'] - med) / med:+.0f}% from the median")
        if m["edge_db"] > -30:
            print(f"  edge: {k} ends at {m['edge_db']} dB (a take that stops mid-sound is taken again)")


if __name__ == "__main__":
    main(sys.argv[1:])
