"""The sound: narration on its words, a few soft UI sounds, a quiet bed under it all, mastered for WhatsApp/YouTube.

    python3 video/mix.py        # -> video/build/mix.wav (48 kHz stereo, -14 LUFS, true peak <= -2 dBTP)

House rules (youtube repo, L18-L21): the narrator is always on top. Effects and the bed sit at least 18 LU under the
voice, nothing piercing in 2-10 kHz (every sound here is a low sine or low-passed noise), effects only where something
happens on screen. Every sound is synthesised here; no sound from WhatsApp itself is used.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SR = 48000
TL = json.loads((BUILD / "timeline.json").read_text())
DUR = TL["duration"]
N = int(DUR * SR) + SR


def env(n, a, d):
    """Attack a seconds, then exponential decay with time constant d."""
    t = np.arange(n) / SR
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-np.maximum(0, t - a) / d)


def tone(freqs, dur, a=0.004, d=0.06, amp=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    return (x * env(n, a, d) * amp).astype(np.float32)


def sweep(f0, f1, dur, a=0.01, d=0.08, amp=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f0 * (f1 / f0) ** (t / dur)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * env(n, a, d) * amp).astype(np.float32)


def noise(dur, lo, hi, a, d, amp, seed=1):
    n = int(dur * SR)
    r = np.random.default_rng(seed).standard_normal(n)
    sos = butter(2, [lo, hi], btype="band", fs=SR, output="sos")
    return (sosfilt(sos, r) * env(n, a, d) * amp).astype(np.float32)


def whoosh(dur=0.7, amp=1.0, seed=3):
    n = int(dur * SR)
    r = np.random.default_rng(seed).standard_normal(n)
    out = np.zeros(n, np.float32)
    # a band that rises then falls, in short blocks
    blk = 512
    for i in range(0, n, blk):
        u = i / n
        fc = 250 + 900 * np.sin(np.pi * u)
        sos = butter(2, [fc * 0.6, fc * 1.4], btype="band", fs=SR, output="sos")
        out[i:i + blk] = sosfilt(sos, r[i:i + blk])
    shape = np.sin(np.pi * np.arange(n) / n) ** 2
    return (out * shape * amp).astype(np.float32)


SFX = {
    "pop": lambda: tone([620, 930], 0.16, a=0.003, d=0.045, amp=0.55),
    "send": lambda: sweep(380, 760, 0.14, a=0.004, d=0.05, amp=0.5),
    "tap": lambda: noise(0.05, 300, 1400, 0.001, 0.012, 0.9),
    "notify": lambda: np.concatenate([tone([660], 0.12, d=0.07, amp=0.5), tone([880], 0.32, d=0.12, amp=0.5)]),
    "whoosh": lambda: whoosh(0.8, 0.5),
    "whoosh_s": lambda: whoosh(0.5, 0.3, seed=5),
}
SFX_DB = {"pop": -24, "send": -25, "tap": -27, "notify": -23, "whoosh": -24, "whoosh_s": -28}


def bed(n):
    """A slow, warm pad: four chords in a low register, eight seconds each, soft attack, low-passed."""
    prog = [[261.63, 329.63, 392.0, 493.88], [220.0, 261.63, 329.63, 392.0], [174.61, 261.63, 349.23, 440.0],
            [196.0, 246.94, 293.66, 392.0]]         # Cmaj7, Am7, Fmaj7(add), G: above 170 Hz, so a phone speaker plays it
    hop, ov = 8.0, 2.5                                 # a chord every 8 s, each fading over the next
    out = np.zeros(n, np.float32)
    t = np.arange(int((hop + ov) * SR)) / SR
    L = hop + ov
    for k, i0 in enumerate(range(0, n, int(hop * SR))):
        ch = prog[k % len(prog)]
        x = np.zeros_like(t)
        for f in ch:
            for det in (-0.6, 0.6):
                x += np.sin(2 * np.pi * (f + det) * t + 0.3 * np.sin(2 * np.pi * 0.11 * t))
        x /= len(ch) * 2
        fade = np.clip(np.minimum(t / ov, (L - t) / ov), 0, 1)
        seg_x = (x * np.sin(0.5 * np.pi * fade) ** 2).astype(np.float32)
        j = min(n, i0 + len(seg_x))
        out[i0:j] += seg_x[:j - i0]
    sos = butter(2, 1500, btype="low", fs=SR, output="sos")
    return sosfilt(sos, out).astype(np.float32)


def db(x):
    return 10 ** (x / 20)


def main():
    voice = np.zeros(N, np.float32)
    for ln in TL["lines"]:
        a, sr = sf.read(BUILD / "narration" / f"{ln['id']}.wav", dtype="float32")
        if sr != SR:
            a = resample_poly(a, SR, sr).astype(np.float32)
        i = int(ln["start"] * SR)
        voice[i:i + len(a)] += a[:N - i]
    fx = np.zeros(N, np.float32)
    last = {}
    for c in TL["sfx"]:
        k = c["kind"]
        if k in last and c["t"] - last[k] < 0.25:      # two of the same sound in a quarter second is one
            continue
        last[k] = c["t"]
        x = SFX[k]() * db(SFX_DB[k])
        i = int(c["t"] * SR)
        fx[i:i + len(x)] += x[:N - i]
    pad = bed(N) * db(-34)
    # duck the bed under speech (a slow envelope of the voice)
    win = int(0.4 * SR)
    cs = np.concatenate([[0.0], np.cumsum(np.abs(voice), dtype=np.float64)])
    idx = np.arange(N)
    v_env = (cs[np.minimum(N, idx + win // 2)] - cs[np.maximum(0, idx - win // 2)]) / win      # moving average
    duck = 1 - 0.45 * np.clip(v_env / 0.02, 0, 1)
    pad *= duck.astype(np.float32)
    # the bed fades in at the start and out at the very end
    fade = np.ones(N, np.float32)
    fade[:SR * 2] = np.linspace(0, 1, SR * 2)
    end = int(DUR * SR)
    fade[end - SR * 3:end] = np.linspace(1, 0, SR * 3)
    fade[end:] = 0
    pad *= fade
    mono = voice + fx + pad
    stereo = np.stack([mono, mono], axis=1)[:end + SR // 2]
    raw = BUILD / "mix_raw.wav"
    sf.write(raw, stereo, SR, subtype="FLOAT")
    for name, x in (("voice", voice), ("fx", fx + pad)):
        sf.write(BUILD / f"stem_{name}.wav", x[:end], SR, subtype="FLOAT")
    # two-pass loudness normalisation to -14 LUFS, true peak -2 dBTP
    first = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(raw), "-af", "loudnorm=I=-14:TP=-2:LRA=11:print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True).stderr
    m = json.loads(first[first.rindex("{"):first.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-2:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af", af, "-c:a", "pcm_s24le",
                    str(BUILD / "mix.wav")], check=True)
    print(f"mix: {end / SR / 60:.2f} min, voice lines {len(TL['lines'])}, sfx {len(TL['sfx'])}; input {m['input_i']} LUFS")


if __name__ == "__main__":
    main()
