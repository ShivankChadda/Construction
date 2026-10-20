"""Put picture and sound together, cut one version per person, and write the subtitles.

    python3 video/deliver.py      # needs video/build/picture.mp4 (web/render.mjs --video) and build/mix.wav (mix.py)

Writes video/output/ (git-ignored; the videos go to Google Drive):
  purchase_desk_tutorial.mp4            the whole film, all chapters
  purchase_desk_for_site_engineers.mp4  opening + site engineers + the whole journey
  purchase_desk_for_abbas.mp4           opening + Abbas + the whole journey
  purchase_desk_for_mr_chadda.mp4       opening + Mr Chadda + the whole journey
  *.hi.srt / *.en.srt                   subtitles: the Hinglish narration as spoken, and its English meaning
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from script import LINE  # noqa: E402

BUILD = HERE / "build"
OUT = HERE / "output"
TL = json.loads((BUILD / "timeline.json").read_text())
MAN = json.loads((BUILD / "narration" / "manifest.json").read_text())
FILM = json.loads((BUILD / "film.json").read_text())
CH = {c["id"]: c["t"] for c in TL["chapters"]}
LINES = {ln["id"]: ln for ln in TL["lines"]}
END = TL["duration"]
CARD = {c["t0"]: c for c in FILM["cards"]}


def run(*cmd):
    subprocess.run(cmd, check=True)


def stamp(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_en(text: str, limit=84) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", text) if p.strip()]
    out = []
    for p in parts:
        while len(p) > limit:
            cut = max(p.rfind(", ", 0, limit), p.rfind(": ", 0, limit))
            if cut < 20:
                cut = p.rfind(" ", 0, limit)
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        out.append(p)
    return out


def cues():
    """[(start, end, hindi, english)] per sentence of the narration, on the voice's own character times."""
    rows = []
    for lid, ln in LINES.items():
        m = MAN[lid]
        text, cs, t0 = m["text"], m["start"], ln["start"]
        bounds = [0] + [mm.end() for mm in re.finditer(r"[।?!]\s+", text)] + [len(text)]
        hi = []
        for a, b in zip(bounds, bounds[1:]):
            s = text[a:b].strip()
            if s:
                hi.append((t0 + cs[a], t0 + (cs[b] if b < len(cs) else ln["dur"]), s))
        en = split_en(LINE[lid]["en"])
        # English pieces share the line's time in proportion to their length
        total = sum(len(e) for e in en)
        t, en_rows = t0, []
        for e in en:
            d = ln["dur"] * len(e) / total
            en_rows.append((t, t + d, e))
            t += d
        rows.append((hi, en_rows))
    return rows


def write_srt(path: Path, items, segments):
    """items: [(start, end, text)] on the film's clock; segments: [(a, b)] of the film kept, in order."""
    n, lines, offset = 0, [], 0.0
    for a, b in segments:
        for s, e, txt in items:
            if s >= a - 0.01 and s < b:
                n += 1
                lines += [str(n), f"{stamp(s - a + offset)} --> {stamp(min(e, b) - a + offset - 0.02)}", txt, ""]
        offset += b - a
    path.write_text("\n".join(lines), encoding="utf-8")


def cut(name: str, segments):
    """Re-encode the kept parts of the film into one file, with a 0.15 s sound fade at each join."""
    src = OUT / "purchase_desk_tutorial.mp4"
    fc, labels = [], []
    for k, (a, b) in enumerate(segments):
        d = b - a
        fc.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{k}]")
        fc.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.15,afade=t=out:st={d - 0.15:.3f}:d=0.15[a{k}]")
        labels.append(f"[v{k}][a{k}]")
    fc.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=1[v][a]")
    tmp = OUT / (name + ".part.mp4")
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-tune", "animation", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(tmp))
    tmp.rename(OUT / (name + ".mp4"))


def main():
    OUT.mkdir(exist_ok=True)
    full = OUT / "purchase_desk_tutorial.mp4"
    tmp = OUT / "purchase_desk_tutorial.part.mp4"
    run("ffmpeg", "-y", "-loglevel", "error", "-i", str(BUILD / "picture.mp4"), "-i", str(BUILD / "mix.wav"), "-map", "0:v",
        "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart",
        str(tmp))
    tmp.rename(full)
    rows = cues()
    hi = [x for h, _ in rows for x in h]
    en = [x for _, e in rows for x in e]
    whole = [(0.0, END)]
    write_srt(OUT / "purchase_desk_tutorial.hi.srt", hi, whole)
    write_srt(OUT / "purchase_desk_tutorial.en.srt", en, whole)
    # one version per person: the opening (without the list of parts), their chapter, and the whole journey
    intro_end = LINES["i6"]["start"] - 0.25
    order = ["engineer", "abbas", "md", "journey"]
    for cid, name in (("engineer", "purchase_desk_for_site_engineers"), ("abbas", "purchase_desk_for_abbas"),
                      ("md", "purchase_desk_for_mr_chadda")):
        nxt = CH[order[order.index(cid) + 1]]
        segs = [(0.0, intro_end), (CH[cid] + 0.4, nxt), (CH["journey"] + 0.4, END)]
        cut(name, segs)
        write_srt(OUT / f"{name}.hi.srt", hi, segs)
        write_srt(OUT / f"{name}.en.srt", en, segs)
    for f in sorted(OUT.glob("*.mp4")):
        d = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                           str(f)]).decode())
        print(f"{f.name:44} {int(d) // 60}:{int(d) % 60:02d}  {f.stat().st_size / 1e6:6.1f} MB")


if __name__ == "__main__":
    main()
