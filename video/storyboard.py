"""The tutorial's storyboard: every bubble, tap, screen, camera move and panel line, placed on the narration.

    python3 video/storyboard.py        # -> video/build/film.json (the web engine draws it) and build/timeline.json

Messages come from the bot itself (video/build/capture.json); the voice from video/build/narration/manifest.json.
A phone on screen is a *view* of one person's chats: the steps before its first live step are history, its live steps
appear on the narration's words, and later steps are left out (no gaps in a chat). A person seen in two chapters has
two views.
"""
from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from capture import POST_DISPATCH, POST_NIC, VOICE_TAMBI  # noqa: E402,F401
from script import CHAPTERS  # noqa: E402

BUILD = HERE / "build"
CAP = json.loads((BUILD / "capture.json").read_text())
MAN = json.loads((BUILD / "narration" / "manifest.json").read_text())
STEPS = {s["id"]: s for s in CAP["steps"]}
ORDER = [s["id"] for s in CAP["steps"]]
SENT = {o["wamid"]: o for s in CAP["steps"] for o in s["out"]}
FPS = 30
MD = "Munishwer Chander Chadda"
MD_SAVED = "Chadda Sahab"        # how the others have him saved

AV = {
    "desk": {"icon": "desk", "color": "#00a884"},
    "group": {"icon": "group", "color": "#7d8f99"},
    "Chandramohan": {"initials": "C", "color": "#ef6c00"},
    "Tambi Uncle": {"initials": "T", "color": "#7b1fa2"},
    "Siddhu": {"initials": "S", "color": "#1565c0"},
    "Ami": {"initials": "A", "color": "#2e7d32"},
    "Abbas": {"initials": "Ab", "color": "#00796b"},
    MD_SAVED: {"initials": "MC", "color": "#c62828"},
    MD: {"initials": "MC", "color": "#c62828"},
    "Shivank": {"initials": "Sh", "color": "#5d4037"},
}
SENDER_COLOR = {"Chandramohan": "#e65100", "Tambi Uncle": "#8e24aa", "Siddhu": "#1e88e5", "Ami": "#43a047",
                "Abbas": "#00897b", MD_SAVED: "#d81b60"}


def clock(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return d.strftime("%I:%M %p").lstrip("0").lower()


def day(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {d.strftime('%B %Y')}"


def photo(lines: str, size=19) -> str:
    return ('<div style="position:absolute;inset:0;background:radial-gradient(circle at 30% 20%,#8a7356,#4a3a28)"></div>'
            f'<div class="paper" style="font-size:{size}px">{lines}</div>')


PHOTO_DIG = photo("Diglipur site\n1. Cement OPC 53\n      30 bag\n2. Gitti 20mm - 4 brass\n3. Welding goggles\n      10 nos")
PHOTO_DSP = photo("Diglipur - Anand Bus\nCement OPC 53 - 30 bag\nGitti 20mm - 4 brass\nWelding goggles - 10\n\n       21/10  Abbas", 18)


def bars(seed, n=34):
    r = random.Random(seed)
    return [round(0.15 + 0.85 * abs(r.gauss(0.45, 0.3)) % 1, 2) for _ in range(n)]


# ================================================================================================ chats


class Chat:
    def __init__(self, cid, title, sub, avatar, kind="bot"):
        self.cid, self.title, self.sub, self.avatar, self.kind = cid, title, sub, avatar, kind
        self.msgs: list[dict] = []
        self.typing, self.select, self.swipes, self.scroll = [], [], [], []
        self.select_clear = None
        self.by_step: dict[str, list[dict]] = {}
        self.n = 0

    def add(self, m: dict, step: str | None = None) -> dict:
        self.n += 1
        m.setdefault("id", f"{self.cid}{self.n}")
        m.setdefault("at", None)
        self.msgs.append(m)
        if step:
            self.by_step.setdefault(step, []).append(m)
        return m

    def spec(self) -> dict:
        out, last_day = [], None
        msgs = [m for m in self.msgs if m["at"] is not None]
        for m in msgs:
            if m.get("iso"):
                d = day(m["iso"])
                if d != last_day:
                    out.append({"id": m["id"] + "d", "type": "date", "text": d, "at": m["at"]})
                    last_day = d
            out.append(m)
        clean = []
        for m in out:
            c = {k: v for k, v in m.items() if k not in ("iso",)}
            clean.append(c)
        sel = [dict(s, until=s.get("until", self.select_clear if self.select_clear is not None else 1e9)) for s in self.select]
        return {"title": self.title, "sub": self.sub, "avatar": self.avatar, "kind": self.kind, "msgs": clean,
                "typing": self.typing, "select": sel, "swipes": self.swipes, "scroll": self.scroll}

    def msg(self, step, k=0, kind=None, contains=""):
        ms = [m for m in self.by_step[step] if (kind is None or m.get("kind0") == kind) and contains in (m.get("text") or "")]
        return ms[k]


def quote_of(wamid: str) -> dict | None:
    s = SENT.get(wamid)
    if not s:
        return None
    first = next((ln for ln in s["body"].splitlines() if ln.strip()), "")
    return {"who": "Purchase Desk", "text": first}


def doc_msg(o: dict, step_iso: str) -> dict:
    path = BUILD / "bot" / o["path"]
    pages = sorted(path.parent.glob(path.stem + ".p*.png"))
    kb = max(1, round(path.stat().st_size / 1024))
    return {"dir": "in", "type": "doc", "kind0": "document", "text": o["body"],
            "doc": {"name": path.name, "meta": f"{len(pages)} page{'s' if len(pages) > 1 else ''} • PDF • {kb} kB",
                    "thumb": "../build/bot/" + str(pages[0].relative_to(BUILD / "bot")),
                    "pages": ["../build/bot/" + str(p.relative_to(BUILD / "bot")) for p in pages]}}


def desk_chat(cid: str, person: str) -> Chat:
    """Everything between `person` and the Purchase Desk, in the bot's own order."""
    c = Chat(cid, "Purchase Desk", "business account", AV["desk"])
    c.add({"type": "sys", "text": "🔒 Messages and calls are end-to-end encrypted. This business uses a secure service "
                                  "from Meta to manage this chat.", "at": -1})
    for sid in ORDER:
        st = STEPS[sid]
        iso = st["time"]
        if st["actor"] == person:
            base = {"dir": "out", "iso": iso, "time": clock(iso), "clock": clock(iso)}
            if st["kind"] == "text":
                m = dict(base, type="text", kind0="in_text", text=st["text"], fwd=st.get("forwarded", False))
                if st.get("quote"):
                    m["quote"] = quote_of(st["quote"])
                c.add(m, sid)
            elif st["kind"] == "audio":
                c.add(dict(base, type="voice", kind0="in_voice", fwd=True,
                           voice={"dur": "0:09", "bars": bars(sid), "avatar": AV["Tambi Uncle"]}), sid)
            elif st["kind"] == "image":
                html = PHOTO_DSP if "Sector" in st["text"] else PHOTO_DIG
                c.add(dict(base, type="image", kind0="in_image", text=st["text"], fwd=st.get("forwarded", False),
                           image={"html": html}), sid)
            elif st["kind"] == "tap":
                c.add(dict(base, type="text", kind0="in_tap", text=st["text"], quote=quote_of(st["on"]), tap_on=st["on"],
                           tap_i=st["button"]), sid)
        for o in st["out"]:
            if o["to"] != person:
                continue
            base = {"dir": "in", "iso": iso, "time": clock(iso), "clock": clock(iso), "wamid": o["wamid"]}
            if o["kind"] == "document":
                c.add(dict(base, **doc_msg(o, iso)), sid)
            elif o["kind"] in ("text", "buttons"):
                c.add(dict(base, type="text", kind0=o["kind"], text=o["body"], buttons=o["buttons"]), sid)
    return c


GROUP = [   # the Kailash Material group, as everyone sees it (the sender's own posts are theirs)
    ("g1", "2026-10-12T09:40", "Chandramohan", "text", "Car Nicobar site requirement\nCement OPC 53 grade 40 bag"),
    ("g2", "2026-10-12T10:20", MD_SAVED, "text", "Abbas do it"),
    ("g3", "2026-10-13T10:05", "Abbas", "text", "Car Nicobar Sector - Cement 40 bag loaded in MV Campbell Bay"),
    ("g_nic", "2026-10-20T09:12", "Chandramohan", "text", POST_NIC),
    ("g_voice", "2026-10-20T09:31", "Tambi Uncle", "voice", ""),
    ("g_photo", "2026-10-20T09:50", "Siddhu", "image", "Diglipur site"),
    ("g_chat", "2026-10-20T10:02", "Ami", "text", "ok sir"),
    ("g_dsp", "2026-10-21T10:28", "Abbas", "image", POST_DISPATCH),
]


def group_chat(cid: str, owner: str) -> Chat:
    c = Chat(cid, "Kailash Material", "Abbas, Ami, Chandramohan, Chadda Sahab, Siddhu, Tambi Uncle", AV["group"], "group")
    c.add({"type": "sys", "text": "🔒 Messages and calls are end-to-end encrypted. Only people in this chat can read, "
                                  "listen to, or share them.", "at": -1})
    for gid, iso, who, kind, text in GROUP:
        mine = who == owner or (owner == MD and who == MD_SAVED)
        m = {"dir": "out" if mine else "in", "iso": iso, "time": clock(iso), "clock": clock(iso), "id": f"{cid}_{gid}"}
        if not mine:
            m.update(sender=who, senderColor=SENDER_COLOR.get(who, "#1f7aec"))
        if kind == "text":
            m.update(type="text", text=text)
        elif kind == "voice":
            m.update(type="voice", voice={"dur": "0:09", "bars": bars(gid), "avatar": AV[who]})
        else:
            m.update(type="image", text=text, image={"html": PHOTO_DSP if gid == "g_dsp" else PHOTO_DIG})
        c.add(m, gid)
    return c


# ================================================================================================ phones


class Phone:
    def __init__(self, pid, tag_hi="", tag_en=""):
        self.pid, self.tag_hi, self.tag_en = pid, tag_hi, tag_en
        self.chats: dict[str, Chat] = {}
        self.screens: list = []
        self.taps: list = []
        self.notifs: list = []
        self.forward = None
        self.pdfs: dict = {}
        FILM.phones[pid] = self

    def chat(self, c: Chat) -> Chat:
        self.chats[c.cid] = c
        return c

    def screen(self, t, key, how="push"):
        self.screens.append([round(t, 3), key, how])

    def tap(self, t, target, hold=0.0, sfx=True, **kw):
        self.taps.append(dict(t=round(t, 3), target=target, hold=hold, **kw))
        if sfx:
            FILM.sfx.append({"t": round(t, 3), "kind": "tap"})

    def spec(self) -> dict:
        return {"tag_hi": self.tag_hi, "tag_en": self.tag_en, "chats": {k: c.spec() for k, c in self.chats.items()},
                "screens": sorted(self.screens, key=lambda s: s[0]), "taps": sorted(self.taps, key=lambda x: x["t"]),
                "notifs": self.notifs, "forward": self.forward, "pdfs": self.pdfs}


class Film:
    def __init__(self):
        self.phones: dict[str, Phone] = {}
        self.layout, self.cam, self.panel, self.persona, self.flow, self.cards = [], [], [], [], [], []
        self.items, self.focus, self.sfx, self.lines, self.chapters = [], [], [], [], []
        self.t = 0.0

    # ------------------------------------------------------------------ time
    def say(self, lid, lead=0.25, tail=0.45) -> "Line":
        L = Line(lid, self.t + lead)
        self.lines.append({"id": lid, "start": round(L.start, 3), "dur": L.dur})
        self.t = L.end + tail
        return L

    def wait(self, s):
        self.t += s

    # ------------------------------------------------------------------ picture
    def lay(self, t, **phones):
        self.layout.append([round(t, 3), phones])

    def look(self, t, **spec):
        self.cam.append([round(t, 3), spec])

    def step(self, t0, t1, h, e="", k="", cmd="", lbl=""):
        if self.panel and t0 < self.panel[-1]["t1"]:     # one card at a time: the earlier one ends first
            self.panel[-1]["t1"] = round(t0 - 0.3, 3)
        self.panel.append(dict(t0=round(t0, 3), t1=round(t1, 3), h=h, e=e, k=k, cmd=cmd, lbl=lbl))

    def ring(self, t0, t1, phone, target, pad=6):
        self.focus.append(dict(t0=round(t0, 3), t1=round(t1, 3), phone=phone, target=target, pad=pad))

    def item(self, t0, t1, **kw):
        self.items.append(dict(t0=round(t0, 3), t1=round(t1, 3), **kw))

    def card(self, n, t, e, w="", dur=3.4):
        t0 = self.t
        self.cards.append(dict(t0=round(t0, 3), t1=round(t0 + dur, 3), n=n, t=t, e=e, w=w))
        self.sfx.append({"t": round(t0, 3), "kind": "whoosh"})
        self.t += dur
        return t0


class Line:
    def __init__(self, lid, start):
        m = MAN[lid]
        self.id, self.start, self.dur, self.text, self.cs = lid, start, m["dur"], m["text"], m["start"]
        self.end = start + self.dur

    def w(self, frag: str, k: int = 0, after=False) -> float:
        """Time the voice says `frag` (its k-th occurrence in the line); after=True: when it finishes it."""
        i = -1
        for _ in range(k + 1):
            i = self.text.find(frag, i + 1)
            if i < 0:
                raise KeyError(f"{self.id}: {frag!r} not in {self.text!r}")
        j = i + len(frag) if after else i
        if j >= len(self.cs):
            return self.end
        return self.start + self.cs[j]


FILM = Film()

SOLO = dict(x=520, y=548, s=1.12, o=1, tag=0)
OFF_L = dict(x=-420, o=0, tag=0)
OFF_R = dict(x=2340, o=0, tag=0)
HIDE = dict(o=0, tag=0)
FLOW_NODES = [
    {"icon": "👷", "hi": "साइट", "en": "Site"},
    {"icon": "📋", "hi": "अब्बास जी", "en": "Abbas"},
    {"icon": "✅", "hi": "चड्ढा साहब", "en": "Approval"},
    {"icon": "🚚", "hi": "डिस्पैच", "en": "Dispatch"},
    {"icon": "📦", "hi": "स्टॉक", "en": "Stock"},
]


def overview(t):
    FILM.look(t, x=960, y=540, z=1)


def zoom(t, phone, target=None, z=1.9, **kw):
    FILM.look(t, phone=phone, target=target, z=z, **kw)


def show(chat: Chat, step: str, t: float, gap=0.55, out_first=True):
    """The messages of one step appear: what the person sent at t, the bot's replies from t + 0.9."""
    ms = chat.by_step.get(step, [])
    k = 0
    tt = t
    for m in ms:
        if m["dir"] == "out":
            m["at"] = round(t, 3)
        else:
            tt = t + 0.9 + gap * k if any(x["dir"] == "out" for x in ms) else t + gap * k
            m["at"] = round(tt, 3)
            if k == 0:
                FILM.sfx.append({"t": round(tt, 3), "kind": "pop"})
            k += 1
    return tt


def history(chat: Chat, before: str, t: float):
    """Every step before `before` is already in the chat at t."""
    for sid in ORDER:
        if sid == before:
            break
        for m in chat.by_step.get(sid, []):
            m["at"] = t


def history_group(chat: Chat, upto: list[str], t: float):
    for gid in upto:
        for m in chat.by_step[gid]:
            m["at"] = t


def type_send(phone: Phone, chat: Chat, text: str, t0: float, t1: float, send: float, quote=None, qt=None):
    chat.typing.append(dict(t0=round(t0, 3), t1=round(t1, 3), send=round(send, 3), text=text,
                            **({"quote": quote, "qt": round(qt, 3)} if quote else {})))
    phone.tap(send, {"el": "send", "chat": chat.cid}, sfx=False)
    FILM.sfx.append({"t": round(send + 0.05, 3), "kind": "send"})


def say_step(phone: Phone, chat: Chat, step: str, t0: float, send: float, cps=11.0, gap=0.55):
    """Type what the person typed in `step` from t0 and send it at `send`; the bot answers."""
    st = STEPS[step]
    text = st["text"]
    t1 = min(send - 0.25, t0 + len(text) / cps)
    type_send(phone, chat, text, t0, t1, send)
    return show(chat, step, send + 0.05, gap=gap)


def tap_step(phone: Phone, chat: Chat, step: str, t: float, gap=0.55):
    """Tap the button `step` tapped; its echo and the bot's reply follow."""
    st = STEPS[step]
    host = next(m for m in chat.msgs if m.get("wamid") == st["on"])
    phone.tap(t, {"btn": [chat.cid, host["id"], st["button"]]})
    return show(chat, step, t + 0.2, gap=gap)


def lines_of(m: dict, *needles: str) -> tuple[int, int]:
    """Index range of the lines of a message that contain the first and last needle."""
    ls = m["text"].split("\n")
    idx = [next(i for i, ln in enumerate(ls) if nd in ln) for nd in needles]
    return min(idx), max(idx)


def mark(m: dict, t0: float, t1: float, *needles: str):
    a, b = lines_of(m, *needles)
    m.setdefault("marks", []).append({"t0": round(t0, 3), "t1": round(t1, 3), "a": a, "b": b})


def lines_target(chat: Chat, m: dict, *needles: str) -> dict:
    a, b = lines_of(m, *needles)
    return {"lines": [chat.cid, m["id"], a, b]}


def flow(t0, t1, *active):
    FILM.flow.append(dict(t0=round(t0, 3), t1=round(t1, 3), active=list(active)))


def persona(t0, t1, name, role, av):
    FILM.persona.append(dict(t0=round(t0, 3), t1=round(t1, 3), name=name, role=role, avatar=av))


# ================================================================================================ chapters


def intro():
    F = FILM
    F.chapters.append(("intro", F.t))
    overview(0)
    t0 = F.t
    F.item(t0, t0 + 3.6, kind="html", cls="title", fin=0.01, html=(
        '<div style="font:700 30px/1 Roboto;letter-spacing:.14em;color:#008069">KEC · KAILASH MATERIAL</div>'
        '<div style="font:700 120px/1.25 \'Noto Sans Devanagari\';color:#12302a;margin-top:24px">पर्चेज़ डेस्क</div>'
        '<div style="font:500 64px/1.2 Roboto;color:#557068;margin-top:6px">Purchase Desk · how it works</div>'
        '<div style="font:500 30px/1.3 \'Noto Sans Devanagari\';color:#557068;margin-top:40px">व्हाट्सऐप पर ख़रीद और अप्रूवल · '
        'Purchases and approvals on WhatsApp</div>'), x=0, y=0)
    F.t += 3.6
    # i1: one phone, the Purchase Desk chat
    ab = Phone("abbas_i")
    desk = ab.chat(desk_chat("d", "Abbas"))
    grp = ab.chat(group_chat("g", "Abbas"))
    ab.screen(0, "chat:d", "cut")
    F.lay(0, abbas_i=dict(OFF_R, x=520, y=548, s=1.12))
    L = F.say("i1", lead=0.2)
    F.lay(L.start, abbas_i=SOLO)
    F.step(L.start, L.end + 0.2, k="पर्चेज़ डेस्क · Purchase Desk", h="एक व्हाट्सऐप नंबर",
           e="One WhatsApp number that keeps track of every requirement, every slip and every approval.")
    zoom(L.w("व्हाट्सऐप"), "abbas_i", {"rect": [0, 40, 393, 60]}, z=2.2, dy=120)
    overview(L.w("हर ज़रूरत"))
    # i2: the group stays as it is
    L = F.say("i2")
    ab.screen(L.w("कैलाश"), "chat:g")
    history_group(grp, [g for g, *_ in GROUP if g != "g_dsp"], 0)
    F.step(L.start, L.w("वह एक क्लर्क"), k="ग्रुप · The group", h="कैलाश मटीरियल ग्रुप वैसे ही चलेगा",
           e="The Kailash Material group keeps running exactly as it does now.")
    F.step(L.w("वह एक क्लर्क"), L.end + 0.2, k="चुपचाप क्लर्क · A silent clerk", h="ग्रुप में कुछ नहीं लिखता",
           e="It never posts in the group. Each person hears only about their own part of the work.")
    # i3 + i4: the flow, person by person
    L3 = F.say("i3", lead=0.3)
    F.lay(L3.start - 0.2, abbas_i=OFF_L)
    xs = [250, 605, 960, 1315, 1670]
    nodes = [("👷", "साइट इंजीनियर", "Site engineers: what's needed"), ("🧾", "अब्बास जी", "Abbas: prices, makes the slip"),
             ("✅", "चड्ढा साहब", "Mr Chadda: approves"), ("🚚", "अब्बास जी", "Abbas: buys, sends"),
             ("📦", "साइट", "Site: confirms → stock")]
    L4_start = F.t + 0.25
    L4 = F.say("i4")
    at = [L3.w("साइट इंजीनियर"), L3.w("अब्बास जी"), L3.w("चड्ढा साहब"), L4.w("ख़रीदते"), L4.w("साइट बटन")]
    end = L4.end + 0.4
    F.item(L3.start, end, kind="html", x=960, y=150, center=True, html=(
        '<div style="font:700 54px/1.3 \'Noto Sans Devanagari\';color:#12302a;text-align:center">काम कैसे चलता है</div>'
        '<div style="font:500 34px/1.3 Roboto;color:#557068;text-align:center">How the work moves</div>'))
    for i, ((ic, hi, en), x, t) in enumerate(zip(nodes, xs, at)):
        F.item(t, end, kind="node", icon=ic, hi=hi, en=en, x=x, y=420, pop=True)
        if i:
            F.item(t - 0.15, end, kind="edge", x=xs[i - 1] + 72, y=480, x2=x - 80, y2=480)
        F.sfx.append({"t": round(t, 3), "kind": "pop"})
    F.item(L4.w("स्टॉक"), end, kind="badge", hi="स्टॉक वही, जो सच में पहुँचा", en="Stock = what really arrived",
           x=960, y=800, center=True, pop=True)
    # i5: everyone saves the number and says hi
    L = F.say("i5", lead=0.4, tail=1.2)
    trio = {}
    for pid, who, hi_, en_ in (("ch_i", "Chandramohan", "चंद्रमोहन · साइट", "Chandramohan · site engineer"),
                               ("ab_i", "Abbas", "अब्बास जी", "Abbas · logistics"),
                               ("md_i", MD, "चड्ढा साहब", "Mr Chadda · approver")):
        p = Phone(pid, hi_, en_)
        c = p.chat(desk_chat("d", who))
        p.screen(0, "chat:d", "cut")
        trio[pid] = (p, c, who)
    xs3 = [400, 960, 1520]
    F.lay(L.start - 0.5, **{pid: dict(x=x, y=600, s=0.9, o=0, tag=0) for pid, x in zip(trio, xs3)})
    F.lay(L.start - 0.3, **{pid: dict(x=x, y=600, s=0.9, o=1, tag=1) for pid, x in zip(trio, xs3)})
    F.item(L.start, L.end + 1.0, kind="html", x=960, y=62, center=True, html=(
        '<div style="font:700 40px/1.3 \'Noto Sans Devanagari\';color:#12302a;white-space:nowrap">नंबर सेव कीजिए: '
        '<span style="color:#008069">Purchase Desk</span> · फिर <span style="color:#008069">hi</span> भेजिए</div>'))
    for k, (pid, (p, c, who)) in enumerate(trio.items()):
        step = "hi_" + who.split()[0].lower()
        t_send = L.w("हाय") + 0.2 + 0.45 * k
        say_step(p, c, step, t_send - 1.0, t_send, gap=0.5)
    # i6: the parts
    L = F.say("i6", lead=0.6, tail=0.8)
    F.lay(L.start - 0.7, **{pid: dict(x=x, y=600, s=0.9, o=0, tag=0) for pid, x in zip(trio, xs3)})
    F.toc = (L.start + 0.7, L.end + 0.6)


def engineer():
    F = FILM
    t_card = F.card("भाग 1 · Part 1", "साइट इंजीनियर", "Site engineers", "Chandramohan · Siddhu · Tambi Uncle · Ami")
    F.chapters.append(("engineer", t_card))
    ch = Phone("ch")
    grp = ch.chat(group_chat("g", "Chandramohan"))
    desk = ch.chat(desk_chat("d", "Chandramohan"))
    history_group(grp, ["g1", "g2", "g3"], t_card)
    history(desk, "summary", t_card)
    ch.screen(0, "chat:g", "cut")
    F.lay(t_card + 1.2, ch=dict(SOLO, o=0))
    F.lay(t_card + 1.8, ch=SOLO)
    overview(t_card)
    persona(F.t, 1e9, "Chandramohan", "साइट इंजीनियर, निकोबार · Site engineer, Nicobar", AV["Chandramohan"])
    p0 = len(F.persona) - 1
    # e1: post in the group as always
    L = F.say("e1", lead=0.5)
    flow(L.start, 1e9, 0)
    f0 = len(F.flow) - 1
    F.step(L.start, L.end, k="स्टेप 1 · Step 1", h="ज़रूरत ग्रुप में डालिए", e="Post the requirement in the group, as before.")
    tp = L.w("ज़रूरत") - 0.3
    type_send(ch, grp, POST_NIC, tp, tp + 3.2, tp + 3.6)
    grp.by_step["g_nic"][0]["at"] = round(tp + 3.65, 3)
    for gid, word in (("g_voice", "वॉइस नोट"), ("g_photo", "फ़ोटो"), ("g_chat", None)):
        if word:
            grp.by_step[gid][0]["at"] = round(L.w(word), 3)
            F.sfx.append({"t": round(L.w(word), 3), "kind": "pop"})
    # e2: name the site
    L = F.say("e2")
    m = grp.by_step["g_nic"][0]
    mark(m, L.w("साइट का नाम"), L.end + 0.3, "Car Nicobar")
    F.step(L.start, L.end, h="मैसेज में साइट का नाम", e="Write the site's name in the message or the photo's caption. Without it, Abbas picks the site with a tap.",
           cmd="Car Nicobar site requirement", lbl="जैसे · for example")
    # e3: Abbas logs it; the engineer hears back
    L = F.say("e3")
    tn = L.w("आपकी ज़रूरत")
    ch.notifs.append({"t0": round(tn, 3), "t1": round(tn + 2.0, 3), "title": "Purchase Desk",
                      "text": "ℹ️ Abbas logged these requirements for Nicobar from the group:"})
    F.sfx.append({"t": round(tn, 3), "kind": "notify"})
    ch.tap(tn + 1.4, {"rect": [10, 8, 373, 72]})
    ch.screen(tn + 1.55, "chat:d")
    show(desk, "summary", tn - 0.05)
    F.step(L.start, L.end, h="दर्ज होते ही आपको मैसेज", e="When Abbas logs it, the Purchase Desk tells you.")
    # e4: every item gets a number
    L = F.say("e4", tail=0.3)
    fyi = desk.by_step["summary"][0]
    zoom(L.start - 0.2, "ch", {"msg": ["d", fyi["id"]]}, z=1.95)
    mark(fyi, L.w("एन फ़ॉर"), L.w("कुछ ग़लत"), "N2", "N4")
    overview(L.w("कुछ ग़लत"))
    F.step(L.w("कुछ ग़लत") + 0.3, L.end + 0.2, h="N निकोबार · K कमोर्टा · D डिगलीपुर",
           e="Every item gets a number. Something wrong? Tell Abbas.")
    # e5: the decision
    L = F.say("e5")
    show(desk, "confirm", L.w("फ़ैसला"))
    F.flow.append(dict(t0=round(L.start, 3), t1=1e9, active=[2]))
    F.flow[f0]["t1"] = round(L.start, 3)
    F.step(L.start, L.end, h="क्या ख़रीदा जाएगा", e="When the slip is decided, you see what will be bought.")
    zoom(L.w("कौन सी चीज़"), "ch", {"msg": ["d", desk.by_step["confirm"][0]["id"]]}, z=1.8)
    overview(L.end + 0.1)
    # e6: the dispatch list
    L = F.say("e6", lead=0.4)
    F.flow[-1]["t1"] = round(L.start, 3)
    flow(L.start, 1e9, 3)
    show(desk, "dsp_nic", L.w("पर्चेज़ डेस्क आपको"), gap=0.8)
    F.step(L.start, L.end + 0.3, k="आपका नया काम · Your one new job", h="सामान भेजा गया",
           e="The Purchase Desk sends the list: what was sent, and on which ship or bus.")
    dsp = desk.by_step["dsp_nic"][0]
    zoom(L.w("क्या गया"), "ch", {"msg": ["d", dsp["id"]]}, z=1.85)
    mark(dsp, L.w("किस जहाज़"), L.end + 0.2, "via MV")
    overview(L.end + 0.2)
    # e7: all received (Siddhu, Diglipur)
    L = F.say("e7", lead=0.6)
    sd = Phone("sd", "सिद्धू · डिगलीपुर", "Siddhu · Diglipur")
    sdesk = sd.chat(desk_chat("d", "Siddhu"))
    history(sdesk, "rcv_dig", t_card)
    sd.screen(0, "chat:d", "cut")
    ch.tag_hi, ch.tag_en = "चंद्रमोहन · निकोबार", "Chandramohan · Nicobar"
    F.lay(L.start - 0.5, ch=dict(x=620, y=612, s=0.92, o=1, tag=1), sd=dict(x=1300, y=612, s=0.92, o=0, tag=0))
    F.lay(L.start - 0.4, sd=dict(x=1300, y=612, s=0.92, o=1, tag=1))
    F.persona[p0]["t1"] = round(L.start - 0.6, 3)
    F.flow[-1]["t1"] = round(L.start - 0.6, 3)
    tap_step(sd, sdesk, "rcv_dig", L.w("ऑल रिसीव्ड") + 0.3)
    F.ring(L.w("ऑल रिसीव्ड") - 0.4, L.w("ऑल रिसीव्ड") + 0.5, "sd",
           {"btn": ["d", next(m["id"] for m in sdesk.msgs if m.get("wamid") == STEPS["rcv_dig"]["on"]), 0]})
    F.item(L.start, L.end + 0.4, kind="html", x=960, y=70, center=True, html=(
        '<div style="font:700 38px/1.3 \'Noto Sans Devanagari\';color:#12302a;white-space:nowrap">सब आया? '
        '<span style="color:#008069">✅ All received</span> दबाइए · <span style="font:500 30px Roboto;color:#557068">'
        'Everything came? Tap it.</span></div>'))
    # e11: forgot? one reminder after two days
    L = F.say("e11", lead=0.5)
    F.lay(L.start - 0.6, ch=SOLO, sd=dict(x=2340, y=612, s=0.92, o=0, tag=0))
    persona(L.start - 0.3, 1e9, "Chandramohan", "साइट इंजीनियर, निकोबार · Site engineer, Nicobar", AV["Chandramohan"])
    p1 = len(F.persona) - 1
    flow(L.start - 0.3, 1e9, 3)
    f1 = len(F.flow) - 1
    show(desk, "remind", L.w("दो दिन बाद"), gap=0.8)
    F.step(L.start, L.end + 0.2, h="भूल गए? एक बार याद दिलाता है", e="Forgot to tap? One reminder after two days.")
    # e8: short or damaged
    L = F.say("e8", lead=0.4)
    tap_step(ch, desk, "short", L.w("शॉर्ट") + 0.4)
    F.step(L.start, L.end + 0.2, h="कम आया? Short/damaged दबाइए", e="Something short or damaged? Tap Short/damaged, then write what came.")
    q = desk.by_step["short"][1]
    zoom(L.w("लिखिए") , "ch", {"msg": ["d", q["id"]]}, z=1.8)
    # e9: 3-2
    L = F.say("e9", tail=0.7)
    mark(q, L.w("रेत"), L.end, "River sand")
    overview(L.w("लाइन तीन"))
    F.step(L.w("लाइन तीन") + 0.2, L.end + 2.6, h="लाइन 3 में 2 आए", e="Line 3, two came: type it like this.",
           cmd="3-2", lbl="लिखिए · type")
    say_step(ch, desk, "short_qty", L.w("थ्री") - 0.1, L.end + 0.3)
    F.wait(1.6)
    # e10: the shortage reaches Abbas and Mr Chadda at once
    L = F.say("e10", lead=0.4, tail=0.8)
    ab = Phone("ab_e", "अब्बास जी", "Abbas")
    adesk = ab.chat(desk_chat("d", "Abbas"))
    history(adesk, "short_qty", t_card)
    ab.screen(0, "chat:d", "cut")
    md = Phone("md_e", "चड्ढा साहब", "Mr Chadda")
    mdesk = md.chat(desk_chat("d", MD))
    history(mdesk, "short_qty", t_card)
    md.screen(0, "chat:d", "cut")
    F.persona[p1]["t1"] = round(L.start - 0.6, 3)
    F.flow[f1]["t1"] = round(L.start - 0.6, 3)
    F.panel[-1]["t1"] = min(F.panel[-1]["t1"], round(L.start - 0.6, 3))
    F.lay(L.start - 0.6, ch=dict(x=400, y=600, s=0.9, o=1, tag=1), ab_e=dict(x=960, y=600, s=0.9, o=0, tag=0),
          md_e=dict(x=1520, y=600, s=0.9, o=0, tag=0))
    F.lay(L.start - 0.4, ab_e=dict(x=960, y=600, s=0.9, o=1, tag=1), md_e=dict(x=1520, y=600, s=0.9, o=1, tag=1))
    ta = L.w("दोनों")
    for c, k in ((adesk, 0), (mdesk, 1)):
        c.by_step["short_qty"][0]["at"] = round(ta + 0.3 * k, 3)
    F.sfx.append({"t": round(ta, 3), "kind": "pop"})
    F.item(L.start, L.end + 0.5, kind="html", x=960, y=70, center=True, html=(
        '<div style="font:700 38px/1.3 \'Noto Sans Devanagari\';color:#12302a;white-space:nowrap">कमी की ख़बर तुरंत · '
        '<span style="font:500 30px Roboto;color:#557068">The shortage reaches Abbas and Mr Chadda at once</span></div>'))
    # e12: usage and stock (optional)
    L = F.say("e12", lead=0.5)
    F.lay(L.start - 0.6, ch=SOLO, ab_e=dict(x=960, y=600, s=0.9, o=0, tag=0), md_e=dict(x=1520, y=600, s=0.9, o=0, tag=0))
    persona(L.start - 0.3, 1e9, "Chandramohan", "साइट इंजीनियर, निकोबार · Site engineer, Nicobar", AV["Chandramohan"])
    p2 = len(F.persona) - 1
    flow(L.start - 0.3, 1e9, 4)
    f2 = len(F.flow) - 1
    F.step(L.start, L.w("और स्टॉक"), k="चाहें तो · Optional", h="इस्तेमाल दर्ज कीजिए", e="Record what was used.",
           cmd="used 10 bag cement", lbl="लिखिए · type")
    say_step(ch, desk, "used", L.w("सामान इस्तेमाल"), L.w("और स्टॉक") - 0.2)
    F.step(L.w("और स्टॉक"), L.end + 1.0, k="चाहें तो · Optional", h="साइट का स्टॉक", e="See the site's stock.",
           cmd="stock", lbl="लिखिए · type")
    say_step(ch, desk, "stock", L.w("और स्टॉक") + 0.2, L.end - 0.3)
    F.wait(0.8)
    # e13: the two things
    L = F.say("e13", lead=0.3, tail=1.2)
    F.step(L.start, L.w("और सामान"), k="याद रखिए · Remember", h="1. ज़रूरत ग्रुप में, साइट के नाम के साथ",
           e="Requirements go in the group, with the site's name.")
    F.step(L.w("और सामान"), L.end + 1.0, k="याद रखिए · Remember", h="2. सामान आए, तो बटन दबाइए",
           e="When material arrives, tap the button.")
    F.persona[p2]["t1"] = round(L.end + 1.0, 3)
    F.flow[f2]["t1"] = round(L.end + 1.0, 3)


def abbas():
    F = FILM
    t_card = F.card("भाग 2 · Part 2", "अब्बास जी", "Abbas · Logistics", "Forward · Slip · Dispatch")
    F.chapters.append(("abbas", t_card))
    overview(t_card)
    ab = Phone("ab")
    grp = ab.chat(group_chat("g", "Abbas"))
    desk = ab.chat(desk_chat("d", "Abbas"))
    history_group(grp, ["g1", "g2", "g3", "g_nic", "g_voice", "g_photo", "g_chat"], t_card)
    history(desk, "fwd_nic", t_card)
    ab.screen(0, "chat:g", "cut")
    ab.forward = {"sub": "", "sections": [
        {"title": "Frequently contacted", "items": [
            {"name": "Purchase Desk", "status": "business account", "avatar": AV["desk"]},
            {"name": MD_SAVED, "status": "", "avatar": AV[MD_SAVED]},
            {"name": "Kailash Material", "status": "group", "avatar": AV["group"]}]},
        {"title": "Recent chats", "items": [
            {"name": n, "status": "", "avatar": AV[n]} for n in ("Chandramohan", "Siddhu", "Tambi Uncle", "Shivank")]}],
        "picks": []}
    F.lay(t_card + 1.2, ch=HIDE, ab=dict(SOLO, o=0))
    F.lay(t_card + 1.8, ab=SOLO)
    persona(F.t, 1e9, "Abbas", "लॉजिस्टिक्स · Logistics", AV["Abbas"])
    p0 = len(F.persona) - 1
    # a1
    L = F.say("a1", lead=0.5)
    flow(L.start, 1e9, 1)
    f0 = len(F.flow) - 1
    F.step(L.start, L.end + 0.2, k="तीन काम · Three jobs", h="1 फ़ॉरवर्ड · 2 स्लिप · 3 डिस्पैच",
           e="Forward from the group · make the slip · send the material")
    # a2: select the group posts
    L = F.say("a2")
    F.step(L.start, L.end + 0.2, k="स्टेप 1 · Step 1", h="एक मैसेज दबाकर रखिए, फिर बाक़ी चुनिए",
           e="Press and hold one requirement post, then tap the other new posts.")
    ids = [grp.by_step[g][0]["id"] for g in ("g_nic", "g_voice", "g_photo", "g_chat")]
    th = L.w("दबाकर रखिए") - 0.2
    ab.tap(th, {"msg": ["g", ids[0]]}, hold=0.7)
    grp.select.append({"t": round(th + 0.7, 3), "msg": ids[0]})
    tt = L.w("टैप करके")
    for k, mid in enumerate(ids[1:]):
        ab.tap(tt + 0.55 * k, {"msg": ["g", mid]})
        grp.select.append({"t": round(tt + 0.55 * k + 0.05, 3), "msg": mid})
    grp.scroll.append({"t": round(th - 1.6, 3), "to": ids[0], "align": "top", "off": -6})
    # a3: forward to the Purchase Desk
    L = F.say("a3")
    tf = L.w("फ़ॉरवर्ड")
    ab.tap(tf + 0.3, {"el": "fwdicon", "chat": "g"})
    ab.screen(tf + 0.5, "fwd")
    tpk = L.w("पर्चेज़ डेस्क चुनिए")
    ab.tap(tpk + 0.1, {"el": "contact", "name": "Purchase Desk"})
    ab.forward["picks"].append({"name": "Purchase Desk", "t": round(tpk + 0.15, 3), "until": round(L.end + 0.6, 3)})
    tsend = L.w("भेज दीजिए")
    ab.tap(tsend + 0.2, {"el": "fwdsend"})
    FILM.sfx.append({"t": round(tsend + 0.25, 3), "kind": "send"})
    grp.select_clear = round(tsend + 0.4, 3)
    ab.screen(tsend + 0.4, "chat:d")
    for k, s in enumerate(("fwd_nic", "fwd_voice", "fwd_photo", "fwd_chat")):
        for m in desk.by_step[s]:
            m["at"] = round(tsend + 0.55 + 0.12 * k, 3)
    F.step(L.start, L.end + 0.2, h="फ़ॉरवर्ड → पर्चेज़ डेस्क", e="Tap Forward, pick Purchase Desk, send.")
    # a4: one summary
    L = F.say("a4", tail=0.3)
    show(desk, "summary", L.w("एक ही समरी") - 0.3, gap=0.9)
    sm = desk.by_step["summary"][0]
    zoom(L.w("एक ही समरी") + 0.4, "ab", {"msg": ["d", sm["id"]]}, z=1.75)
    mark(sm, L.w("एक ही समरी") + 0.6, L.end + 0.2, "NICOBAR", "N4")
    mark(sm, L.w("एक ही समरी") + 0.9, L.end + 0.2, "DIGLIPUR", "D3")
    F.step(L.start, L.w("एक ही समरी"), h="हर पोस्ट पढ़कर, साइट के हिसाब से", e="It reads every post, the voice note and the photo too.")
    # a5: chat is skipped
    L = F.say("a5", tail=0.3)
    mark(sm, L.start, L.end + 0.2, "No materials")
    zoom(L.start - 0.2, "ab", lines_target(desk, sm, "No materials"), z=2.0)
    # a6: the site buttons
    L = F.say("a6", tail=0.6)
    sb = desk.by_step["summary"][1]
    zoom(L.start - 0.1, "ab", {"msg": ["d", sb["id"]]}, z=1.8, dy=40)
    tap_step(ab, desk, "site_kam", L.w("सही साइट") + 0.4, gap=0.9)
    zoom(L.end - 0.6, "ab", {"msg": ["d", desk.by_step["site_kam"][1]["id"]]}, z=1.8)
    # a7: fixing a logged item
    L = F.say("a7", lead=0.3)
    overview(L.start - 0.3)
    F.step(L.start, L.w("और कोई चीज़"), h="मात्रा ग़लत है?", e="Wrong quantity? Type the item number and the right quantity.",
           cmd="N2 60 bag", lbl="लिखिए · type")
    F.step(L.w("और कोई चीज़"), L.end + 0.3, h="कोई चीज़ हटानी है?", e="Take an item off the list.", cmd="remove N2",
           lbl="लिखिए · type")
    # a8: list
    L = F.say("a8")
    F.flow[f0]["t1"] = round(L.start, 3)
    flow(L.start, 1e9, 1)
    f1 = len(F.flow) - 1
    F.step(L.start, L.end + 0.3, k="स्टेप 2 · Step 2", h="लिस्ट लिखिए", e="All open requirements by site, with a PDF for the market.",
           cmd="list", lbl="लिखिए · type")
    say_step(ab, desk, "list", L.w("लिस्ट लिखिए"), L.w("सारी खुली") - 0.1, gap=1.0)
    lst = desk.by_step["list"][1]
    zoom(L.w("साइट के हिसाब"), "ab", {"msg": ["d", lst["id"]]}, z=1.7, dy=-60)
    zoom(L.w("एक पीडीएफ़"), "ab", {"msg": ["d", desk.by_step["list"][2]["id"]]}, z=1.8)
    overview(L.end + 0.2)
    # a9: the slip lines
    L = F.say("a9", tail=0.4)
    F.step(L.start, L.end + 3.2, h="आइटम · दुकान · रेट", e="Item number, shop, rate. One shop and one rate per line.",
           cmd="N2 Om Traders 420\nN3 Hira Metals 62000\nK2 Sagar Hardware 1450", lbl="जैसे · for example")
    ts = L.w("आइटम का नंबर")
    say_step(ab, desk, "slip", ts, L.end + 2.8, cps=22, gap=1.2)
    F.wait(2.6)
    # a10: the slip with its checks
    L = F.say("a10", tail=0.3)
    slip = desk.by_step["slip"][1]
    desk.scroll.append({"t": round(L.start + 0.1, 3), "to": slip["id"], "align": "top"})
    zoom(L.start + 0.2, "ab", {"msg": ["d", slip["id"]]}, z=1.55, anchor="top")
    # a11: the alerts
    L = F.say("a11", tail=0.4)
    tr = L.w("सीमेंट का रेट")
    mark(slip, tr, L.end + 0.4, "Rate ₹420 is 6.3% above last ₹395 (Om Traders, 12 Oct 2026)")
    zoom(tr - 0.3, "ab", lines_target(desk, slip, "1. Cement", "Already bought"), z=2.0)
    tb = L.w("निकोबार के लिए")
    mark(slip, tb, L.end + 0.4, "Already bought")
    tv = L.w("सागर हार्डवेयर")
    desk.scroll.append({"t": round(tv - 0.6, 3), "to": slip["id"], "align": "top", "off": 250})
    zoom(tv - 0.5, "ab", lines_target(desk, slip, "5. Shuttering", "New vendor"), z=2.0)
    mark(slip, tv, L.end + 0.4, "New vendor")
    # a12: send for approval
    L = F.say("a12", tail=0.6)
    desk.scroll.append({"t": round(L.start, 3), "to": desk.by_step["slip"][2]["id"], "align": "bottom"})
    overview(L.start)
    F.step(L.start + 0.3, L.end + 0.4, h="📤 Send for approval दबाइए", e="Mr Chadda sees the same warnings. All in order? Send.")
    tap_step(ab, desk, "send", L.w("सेंड फ़ॉर") + 0.6, gap=0.8)
    # a13: a question comes; swipe to answer
    L = F.say("a13", tail=0.5)
    F.flow[f1]["t1"] = round(L.start, 3)
    flow(L.start, 1e9, 2)
    f2 = len(F.flow) - 1
    show(desk, "ask", L.w("सवाल यहाँ") - 0.2)
    qm = desk.by_step["ask"][0]
    tsw = L.w("स्वाइप")
    desk.swipes.append({"t": round(tsw, 3), "msg": qm["id"]})
    ab.tap(tsw - 0.05, {"msg": ["d", qm["id"]]}, sfx=False, fx=0.2)
    ans = STEPS["answer"]["text"]
    tsend = L.end + 1.6
    type_send(ab, desk, ans, L.w("जवाब लिखिए"), L.w("जवाब लिखिए") + 2.4, tsend, quote=quote_of(STEPS["answer"]["quote"]),
              qt=tsw + 0.35)
    show(desk, "answer", tsend + 0.05)
    F.step(L.start, L.end + 2.2, k="सवाल का जवाब · Answering", h="मैसेज को दाईं ओर स्वाइप कीजिए",
           e="Swipe the question to the right, type your answer, send. It goes straight to Mr Chadda.")
    F.wait(2.0)
    # a14: the signed slip
    L = F.say("a14", tail=0.3)
    show(desk, "confirm", L.w("साइन की हुई") - 0.3, gap=0.9)
    pa = desk.by_step["confirm"][0]
    zoom(L.w("यहाँ लाइन"), "ab", lines_target(desk, pa, "PARTLY", "5. Shuttering"), z=1.9)
    mark(pa, L.w("यहाँ लाइन"), L.end + 6.5, "Not approved", "5. Shuttering")
    # a15: the rule
    L = F.say("a15", lead=0.3)
    mark(pa, L.start, L.end + 0.5, "Buy only")
    zoom(L.start - 0.2, "ab", lines_target(desk, pa, "Verification", "Buy only"), z=1.9)
    overview(L.end - 0.6)
    F.step(L.end - 0.5, L.end + 0.8, k="नियम · The rule", h="सिर्फ़ साइन की हुई स्लिप का सामान",
           e="Buy only what the signed slip says, from the shop it names.")
    # a19: the morning list
    L = F.say("a19", lead=0.5)
    F.flow[f2]["t1"] = round(L.start, 3)
    flow(L.start, 1e9, 3)
    f3 = len(F.flow) - 1
    show(desk, "evening", L.w("आठ बजे"))      # nothing for Abbas in the evening tick; kept for the order
    show(desk, "morning", L.w("आज की लिस्ट") - 0.2)
    F.step(L.start, L.end + 0.3, k="हर सुबह 8 बजे · Every morning", h="आज की लिस्ट",
           e="What each site is waiting for, and what is approved but not yet sent.")
    zoom(L.w("आज की लिस्ट") + 0.3, "ab", {"msg": ["d", desk.by_step["morning"][0]["id"]]}, z=2.0)
    overview(L.end)
    # a16: post the dispatch in the group, then forward it
    L = F.say("a16", tail=0.4)
    F.step(L.start, L.end + 3.0, k="स्टेप 3 · Step 3", h="भेजने की पोस्ट भी फ़ॉरवर्ड",
           e="Post the dispatch in the group as now (photo + which bus or ship), then forward it too.")
    ab.screen(L.start + 0.2, "chat:g", "pop")
    gd = grp.by_step["g_dsp"][0]
    gd["at"] = round(L.w("लिस्ट की फ़ोटो"), 3)
    F.sfx.append({"t": gd["at"], "kind": "send"})
    th = L.w("फिर वह पोस्ट")
    sel_clear_2 = L.end + 1.6
    grp.select.append({"t": round(th + 0.6, 3), "msg": gd["id"], "until": round(sel_clear_2, 3)})
    ab.tap(th, {"msg": ["g", gd["id"]]}, hold=0.6)
    # the second forward uses the same picker
    ab.tap(th + 1.2, {"el": "fwdicon", "chat": "g"})
    ab.screen(th + 1.4, "fwd")
    ab.tap(th + 2.0, {"el": "contact", "name": "Purchase Desk"})
    ab.forward["picks"].append({"name": "Purchase Desk", "t": round(th + 2.05, 3), "until": round(sel_clear_2 + 0.5, 3)})
    ab.tap(sel_clear_2 - 0.25, {"el": "fwdsend"})
    FILM.sfx.append({"t": round(sel_clear_2 - 0.2, 3), "kind": "send"})
    ab.screen(sel_clear_2, "chat:d")
    for m in desk.by_step["dsp_dig"]:
        if m["dir"] == "out":
            m["at"] = round(sel_clear_2 + 0.15, 3)
    F.wait(1.6)
    # a17: matched and the site is asked
    L = F.say("a17", tail=0.4)
    rep = [m for m in desk.by_step["dsp_dig"] if m["dir"] == "in"][0]
    rep["at"] = round(L.w("मिलाता है") - 0.3, 3)
    F.sfx.append({"t": rep["at"], "kind": "pop"})
    zoom(L.w("मिलाता है"), "ab", {"msg": ["d", rep["id"]]}, z=1.9)
    mark(rep, L.w("मिलाता है"), L.end + 0.3, "matched")
    mark(rep, L.w("साइट से पूछता"), L.end + 0.3, "will confirm")
    # a18: or type it
    L = F.say("a18", tail=0.6)
    overview(L.start - 0.2)
    F.step(L.start, L.end + 2.0, h="या सीधे लिखिए", e="No group post? Type the dispatch directly.",
           cmd="dispatch PS-0002 Nicobar MV Campbell Bay", lbl="लिखिए · type")
    say_step(ab, desk, "dsp_nic", L.w("डिस्पैच"), L.end + 0.6, cps=16)
    F.wait(1.4)
    # a20: the three things
    L = F.say("a20", lead=0.3, tail=1.2)
    F.step(L.start, L.end + 1.0, k="याद रखिए · Remember", h="ग्रुप से फ़ॉरवर्ड · लाइन लिखकर स्लिप · डिस्पैच भी फ़ॉरवर्ड",
           e="Forward from the group · write lines for the slip · forward the dispatch post too")
    F.persona[p0]["t1"] = round(L.end + 1.0, 3)
    F.flow[f3]["t1"] = round(L.end + 1.0, 3)


def chadda():
    F = FILM
    t_card = F.card("भाग 3 · Part 3", "चड्ढा साहब", "Mr Chadda · Approval", "Munishwer Chander Chadda")
    F.chapters.append(("md", t_card))
    overview(t_card)
    md = Phone("md")
    desk = md.chat(desk_chat("d", MD))
    grp = md.chat(group_chat("g", MD))
    history(desk, "send", t_card)
    history_group(grp, ["g1", "g2", "g3", "g_nic", "g_voice", "g_photo", "g_chat"], t_card)
    md.screen(0, "chat:d", "cut")
    F.lay(t_card + 1.2, ab=HIDE, md=dict(SOLO, o=0))
    F.lay(t_card + 1.8, md=SOLO)
    persona(F.t, 1e9, "Munishwer Chander Chadda", "अप्रूवर · Approver (Managing Director)", AV[MD])
    p0 = len(F.persona) - 1
    # m1: the slip arrives
    L = F.say("m1", lead=0.6)
    flow(L.start, 1e9, 2)
    f0 = len(F.flow) - 1
    tn = L.start + 0.2
    md.notifs.append({"t0": round(tn, 3), "t1": round(tn + 2.2, 3), "title": "Purchase Desk", "text": "📄 PS-0002 — for your approval"})
    F.sfx.append({"t": round(tn, 3), "kind": "notify"})
    ms = desk.by_step["send"]
    ms[0]["at"] = round(L.w("पहले पीडीएफ़"), 3)
    ms[1]["at"] = round(L.w("फिर पूरी लिस्ट"), 3)
    ms[2]["at"] = round(L.w("नीचे तीन बटन"), 3)
    F.sfx.append({"t": ms[0]["at"], "kind": "pop"})
    F.step(L.start, L.end + 0.3, k="स्लिप आई · A slip arrives", h="पीडीएफ़, पूरी लिस्ट, तीन बटन",
           e="Every slip comes to you here: the PDF, the full list, and three buttons.")
    desk.scroll.append({"t": round(L.w("फिर पूरी लिस्ट") + 0.6, 3), "to": ms[1]["id"], "align": "top"})
    desk.scroll.append({"t": round(L.w("नीचे तीन बटन") + 0.1, 3), "to": ms[2]["id"], "align": "bottom"})
    zoom(L.w("नीचे तीन बटन") + 0.2, "md", {"msg": ["d", ms[2]["id"]]}, z=1.7, dy=40)
    # m2 + m3: reading the lines and the yellow signs
    L = F.say("m2", lead=0.3, tail=0.3)
    slip = ms[1]
    desk.scroll.append({"t": round(L.start - 0.3, 3), "to": slip["id"], "align": "top"})
    zoom(L.start, "md", lines_target(desk, slip, "1. Cement", "Om Traders · N2"), z=2.0)
    mark(slip, L.w("साइट"), L.w("जिस लाइन"), "1. Cement", "Om Traders · N2")
    ty = L.w("पीला निशान")
    mark(slip, ty, ty + 9.0, "Rate ₹420 is 6.3% above last ₹395 (Om Traders, 12 Oct 2026)", "Already bought")
    zoom(ty - 0.3, "md", lines_target(desk, slip, "1. Cement", "Already bought"), z=2.0)
    L = F.say("m3", tail=0.4)
    tv = L.w("दुकान नई")
    desk.scroll.append({"t": round(tv - 0.5, 3), "to": slip["id"], "align": "top", "off": 250})
    zoom(tv - 0.4, "md", lines_target(desk, slip, "5. Shuttering", "New vendor"), z=2.0)
    mark(slip, tv, L.end + 0.3, "New vendor")
    tr = L.w("दस दिन")
    desk.scroll.append({"t": round(tr - 0.5, 3), "to": slip["id"], "align": "top"})
    zoom(tr - 0.4, "md", lines_target(desk, slip, "1. Cement", "Already bought"), z=2.0)
    # m4: ask a question
    L = F.say("m4", lead=0.4)
    desk.scroll.append({"t": round(L.start - 0.3, 3), "to": ms[2]["id"], "align": "bottom"})
    overview(L.start - 0.3)
    F.step(L.start, L.end + 2.0, k="सवाल · A question", h="बस लिख दीजिए", e="Just type it. It goes to Abbas.",
           cmd="cement 420 kyun?", lbl="जैसे · for example")
    say_step(md, desk, "ask", L.w("जैसे"), L.end + 0.5, cps=9)
    F.wait(1.0)
    # m5: the slip waits; Abbas answers
    L = F.say("m5", tail=0.4)
    show(desk, "answer", L.w("उनका जवाब") - 0.2)
    F.step(L.start, L.end + 0.3, h="स्लिप इंतज़ार करती है", e="The slip waits for your decision. Abbas's answer comes here.")
    zoom(L.w("उनका जवाब") + 0.4, "md", {"msg": ["d", desk.by_step["answer"][0]["id"]]}, z=1.9)
    # m6 + m7: how to decide
    L = F.say("m6", lead=0.4)
    overview(L.start - 0.3)
    F.step(L.start, L.w("नहीं,"), k="फ़ैसला · Deciding", h="पूरी स्लिप मंज़ूर", e="Approve the whole slip",
           cmd="haan   ok   Abbas do it", lbl="इनमें से कोई · any of these")
    F.step(L.w("नहीं,"), L.end + 0.3, k="फ़ैसला · Deciding", h="पूरी स्लिप नामंज़ूर", e="Reject the whole slip", cmd="nahi",
           lbl="लिखिए · type")
    L = F.say("m7")
    F.step(L.start, L.w("और कुछ ही"), k="फ़ैसला · Deciding", h="एक लाइन रोकनी है", e="Everything except line 5",
           cmd="5 nahi", lbl="लिखिए · type")
    F.step(L.w("और कुछ ही"), L.end + 0.3, k="फ़ैसला · Deciding", h="कुछ ही लाइनें मंज़ूर", e="Only lines 1 and 2",
           cmd="only 1 2", lbl="लिखिए · type")
    # m8: 5 nahi, confirm
    L = F.say("m8", tail=0.6)
    F.step(L.start, L.end + 0.4, h="पाँच नहीं → कन्फ़र्म", e="Sagar Hardware is new: “5 nahi”, check, then Confirm.",
           cmd="5 nahi", lbl="लिखिए · type")
    say_step(md, desk, "decide", L.w("फ़ाइव") - 0.4, L.w("पर्चेज़ डेस्क एक बार") - 0.2, cps=7, gap=0.6)
    cf = desk.by_step["decide"][1]
    zoom(L.w("क्या मंज़ूर"), "md", {"msg": ["d", cf["id"]]}, z=1.9, dy=30)
    mark(cf, L.w("क्या मंज़ूर"), L.end + 0.3, "Approve line", "Reject line")
    tap_step(md, desk, "confirm", L.w("कन्फ़र्म दबाइए") + 0.4, gap=0.8)
    # m9 + m10: the signed slip
    L = F.say("m9", lead=0.5, tail=0.3)
    overview(L.start - 0.4)
    signed = desk.by_step["confirm"][2]
    md.pdfs["signed"] = {"name": signed["doc"]["name"], "pages": signed["doc"]["pages"], "clock": signed["clock"],
                         "scroll": []}
    md.tap(L.start + 0.3, {"doc": ["d", signed["id"]]})
    md.screen(L.start + 0.5, "pdf:signed")
    md.pdfs["signed"]["scroll"].append([round(L.start + 1.2, 3), 528])
    zoom(L.w("आपके नाम") - 0.2, "md", {"el": "pdfpage", "pdf": "signed", "page": 1}, z=3.0, dy=-202)
    F.step(L.start, L.end, h="साइन की हुई स्लिप", e="Your name, your initials stamp, date, time and a verification code.")
    L = F.say("m10", tail=0.4)
    zoom(L.w("क्यूआर") - 0.3, "md", {"el": "pdfpage", "pdf": "signed", "page": 1}, z=3.4, dy=-202, dx=110)
    # m11: only his number
    L = F.say("m11", lead=0.4, tail=0.4)
    md.screen(L.start - 0.2, "chat:d", "pop")
    overview(L.start - 0.3)
    F.step(L.start, L.end + 0.4, k="सबसे ज़रूरी · Most important", h="अप्रूवल सिर्फ़ आपके नंबर से",
           e="Only your number can approve. Without your yes, no slip carries your name.")
    # m12: buttons and voice
    L = F.say("m12", lead=0.3)
    desk.scroll.append({"t": round(L.start - 0.2, 3), "to": ms[2]["id"], "align": "bottom", "off": 40})
    F.ring(L.w("अप्रूव ऑल") - 0.3, L.w("वॉइस नोट"), "md", {"msg": ["d", ms[2]["id"]]})
    F.step(L.start, L.w("वॉइस नोट"), h="बटन भी काम करते हैं", e="Approve all · Reject · Ask logistics")
    F.step(L.w("वॉइस नोट"), L.end + 0.3, h="वॉइस नोट से जवाब?", e="It shows what it heard; you tap Confirm.")
    # m14: the evening summary
    L = F.say("m14", lead=0.4)
    desk.scroll.append({"t": round(L.start - 0.2, 3), "to": desk.by_step["confirm"][2]["id"], "align": "bottom"})
    show(desk, "evening", L.w("एक समरी") - 0.3)
    ev = desk.by_step["evening"][0]
    zoom(L.w("एक समरी") + 0.3, "md", {"msg": ["d", ev["id"]]}, z=1.7)
    overview(L.w("कभी भी"))
    F.step(L.w("कभी भी"), L.w("और पेंडिंग"), k="कभी भी · Any time", h="इस महीने का हिसाब", e="This month's spending",
           cmd="report", lbl="लिखिए · type")
    F.step(L.w("और पेंडिंग"), L.end + 0.3, k="कभी भी · Any time", h="जो स्लिप इंतज़ार में हैं", e="Slips waiting for you",
           cmd="pending", lbl="लिखिए · type")
    # m13: a shortage
    L = F.say("m13", lead=0.4, tail=0.5)
    show(desk, "short_qty", L.w("कुछ कम") + 0.2)
    F.flow[f0]["t1"] = round(L.start, 3)
    flow(L.start, 1e9, 3, 4)
    f1 = len(F.flow) - 1
    F.step(L.start, L.end + 0.4, h="कमी की ख़बर उसी समय", e="A short delivery reaches you the moment the site reports it.")
    zoom(L.w("ख़बर") , "md", {"msg": ["d", desk.by_step["short_qty"][0]["id"]]}, z=2.0)
    # m15: the group
    L = F.say("m15", lead=0.4, tail=1.2)
    overview(L.start - 0.3)
    md.screen(L.start, "chat:g", "pop")
    g2 = grp.by_step["g2"][0]
    F.step(L.start, L.end + 1.0, k="ग्रुप में · In the group", h="हर चीज़ पर “Abbas do it” ज़रूरी नहीं",
           e="Say yes on the slip instead: that is where you see the rate.")
    grp.scroll.append({"t": round(L.start + 0.2, 3), "to": g2["id"], "align": "center"})
    F.ring(L.w("अब्बास डू इट") - 0.2, L.end, "md", {"msg": ["g", g2["id"]]})
    F.persona[p0]["t1"] = round(L.end + 1.0, 3)
    F.flow[f1]["t1"] = round(L.end + 1.0, 3)


def journey():
    F = FILM
    t_card = F.card("आख़िर में · Finally", "पूरा सफ़र", "The whole journey", dur=3.0)
    F.chapters.append(("journey", t_card))
    overview(t_card)
    xs = [400, 960, 1520]
    P = {}
    for pid, who, hi_, en_ in (("ch_j", "Chandramohan", "साइट · चंद्रमोहन", "Site · Chandramohan"),
                               ("ab_j", "Abbas", "अब्बास जी", "Abbas"),
                               ("md_j", MD, "चड्ढा साहब", "Mr Chadda")):
        p = Phone(pid, hi_, en_)
        d = p.chat(desk_chat("d", who))
        g = p.chat(group_chat("g", who))
        history(d, "evening2", t_card)
        history_group(g, [x[0] for x in GROUP], t_card)
        P[pid] = (p, d, g)
    F.lay(t_card + 0.6, md=HIDE, **{pid: dict(x=x, y=628, s=0.84, o=0, tag=0) for pid, x in zip(P, xs)})
    F.lay(t_card + 1.4, **{pid: dict(x=x, y=628, s=0.84, o=1, tag=1) for pid, x in zip(P, xs)})
    ch, cd, cg = P["ch_j"]
    ab, ad, ag = P["ab_j"]
    md, mdd, _ = P["md_j"]
    ch.screen(0, "chat:g", "cut")
    ab.screen(0, "chat:d", "cut")
    md.screen(0, "chat:d", "cut")
    L = F.say("j1", lead=0.5)
    cg.scroll.append({"t": round(t_card + 1.0, 3), "to": cg.by_step["g_nic"][0]["id"], "align": "center"})
    ad.scroll.append({"t": round(t_card + 1.0, 3), "to": ad.by_step["summary"][0]["id"], "align": "top"})
    mdd.scroll.append({"t": round(t_card + 1.0, 3), "to": mdd.by_step["send"][2]["id"], "align": "bottom"})

    def token(t0, t1, text, a, b, y=100):    # above the phones and their name tags: never over a chat
        F.item(t0, t1 + 0.6, kind="token", text=text, center=True, path=[[t0, a, y], [t1, b, y]], x=a, y=y)
        F.sfx.append({"t": round(t0, 3), "kind": "whoosh_s"})

    L = F.say("j2", tail=0.4)
    F.ring(L.start, L.w("अब्बास जी"), "ch_j", {"msg": ["g", cg.by_step["g_nic"][0]["id"]]})
    token(L.w("अब्बास जी") - 0.2, L.w("अब्बास जी") + 0.8, "📋 ज़रूरत · requirement", 400, 960)
    F.ring(L.w("फ़ॉरवर्ड") , L.w("रेट लगाकर"), "ab_j", {"msg": ["d", ad.by_step["summary"][0]["id"]]})
    ad.scroll.append({"t": round(L.w("रेट लगाकर") - 0.3, 3), "to": ad.by_step["send"][1]["id"], "align": "bottom"})
    F.ring(L.w("रेट लगाकर"), L.end + 0.3, "ab_j", {"msg": ["d", ad.by_step["send"][1]["id"]]})
    token(L.w("स्लिप भेजते"), L.w("स्लिप भेजते") + 1.0, "🧾 PS-0002", 960, 1520)
    L = F.say("j3", tail=0.4)
    mdd.scroll.append({"t": round(L.start, 3), "to": mdd.by_step["confirm"][0]["id"], "align": "bottom"})
    F.ring(L.start + 0.2, L.w("साइन की हुई"), "md_j", {"msg": ["d", mdd.by_step["decide"][0]["id"]]})
    token(L.w("साइन की हुई"), L.w("साइन की हुई") + 1.0, "✅ साइन की हुई स्लिप · signed", 1520, 960)
    ad.scroll.append({"t": round(L.w("साइन की हुई") + 0.6, 3), "to": ad.by_step["confirm"][0]["id"], "align": "top"})
    F.ring(L.w("साइन की हुई") + 0.8, L.w("साइट को"), "ab_j", {"msg": ["d", ad.by_step["confirm"][0]["id"]]})
    ch.screen(L.w("साइट को") - 0.4, "chat:d")
    cd.scroll.append({"t": round(L.w("साइट को") - 0.4, 3), "to": cd.by_step["confirm"][0]["id"], "align": "center"})
    token(L.w("साइट को") - 0.3, L.w("साइट को") + 0.7, "🧾 क्या ख़रीदा जाएगा", 960, 400)
    F.ring(L.w("साइट को") + 0.6, L.end + 0.3, "ch_j", {"msg": ["d", cd.by_step["confirm"][0]["id"]]})
    L = F.say("j4", tail=0.6)
    token(L.start, L.start + 1.0, "🚚 DSP-0003", 960, 400)
    cd.scroll.append({"t": round(L.start + 0.6, 3), "to": cd.by_step["short_qty"][0]["id"], "align": "bottom"})
    F.ring(L.w("साइट बटन"), L.w("स्टॉक"), "ch_j", {"msg": ["d", cd.by_step["short_qty"][0]["id"]]})
    cd.scroll.append({"t": round(L.w("स्टॉक") - 0.3, 3), "to": cd.by_step["stock"][1]["id"], "align": "bottom"})
    F.ring(L.w("स्टॉक"), L.w("गूगल जुड़ने"), "ch_j", {"msg": ["d", cd.by_step["stock"][1]["id"]]})
    F.item(L.w("गूगल जुड़ने"), L.end + 0.5, kind="badge", hi="🗂 गूगल ड्राइव  ·  📊 गूगल शीट",
           en="Once Google is connected: every decided slip in Drive, every line in the Sheet", x=960, y=108, center=True,
           pop=True)
    L = F.say("j5", lead=0.4, tail=2.6)
    F.lay(L.start - 0.3, **{pid: dict(x=x, y=628, s=0.84, o=0, tag=0) for pid, x in zip(P, xs)})
    F.item(L.start, L.end + 2.6, kind="html", x=960, y=520, center=True, fout=0.6, html=(
        '<div style="text-align:center"><div style="font:700 66px/1.3 \'Noto Sans Devanagari\';color:#12302a">कोई दिक़्क़त? '
        '<span style="color:#008069">hi</span> भेजिए</div>'
        '<div style="font:500 40px/1.3 Roboto;color:#557068;margin-top:8px">Any trouble? Send “hi” to the Purchase Desk, '
        'or tell Shivank.</div>'
        '<div style="font:700 80px/1.3 \'Noto Sans Devanagari\';color:#008069;margin-top:60px">धन्यवाद · Thank you</div></div>'))


def toc():
    F = FILM
    t0, t1 = F.toc
    names = {c[0]: c for c in CHAPTERS}
    rows = []
    for k, (cid, t) in enumerate(F.chapters[1:], start=1):
        _, hi, en, _ = names[cid]
        m, s = divmod(int(t), 60)
        rows.append(f'<div class="r" style="opacity:1"><span class="tm">{m}:{s:02d}</span><span class="tt">{hi}</span>'
                    f'<span class="te">{en}</span></div>')
    F.item(t0, t1, kind="html", cls="toc", x=500, y=300, html="".join(rows) +
           '<div style="font:500 26px/1.3 \'Noto Sans Devanagari\';color:#557068;margin-top:20px">अपने हिस्से पर सीधे जाइए · '
           'Skip to your own part</div>')


def validate(film):
    """Every message a scroll, tap, ring or camera move points at is in its chat (has a time)."""
    bad = []
    for pid, ph in film["phones"].items():
        ids = {cid: {m["id"]: m for m in c["msgs"]} for cid, c in ph["chats"].items()}
        for cid, c in ph["chats"].items():
            for s in c["scroll"]:
                if s["to"] not in ids[cid]:
                    bad.append(f"{pid}/{cid}: scroll at {s['t']} to dropped {s['to']}")
            for s in c["select"]:
                if s["msg"] not in ids[cid]:
                    bad.append(f"{pid}/{cid}: select of dropped {s['msg']}")
        refs = [("tap", tp["t"], tp["target"]) for tp in ph["taps"]]
        refs += [("ring", f["t0"], f["target"]) for f in film["focus"] if f["phone"] == pid]
        refs += [("cam", t, sp["target"]) for t, sp in film["cam"] if sp.get("phone") == pid and sp.get("target")]
        for kind, t, tg in refs:
            for key in ("btn", "msg", "doc", "lines"):
                if key in tg:
                    cid, mid = tg[key][0], tg[key][1]
                    if mid not in ids.get(cid, {}):
                        bad.append(f"{pid}/{cid}: {kind} at {t} on dropped {mid}")
                    elif ids[cid][mid]["at"] > t + 0.01 and kind != "cam":
                        bad.append(f"{pid}/{cid}: {kind} at {t} before {mid} appears ({ids[cid][mid]['at']})")
    if bad:
        raise SystemExit("storyboard problems:\n  " + "\n  ".join(bad))


def build():
    intro()
    engineer()
    abbas()
    chadda()
    journey()
    toc()
    F = FILM
    dur = round(F.t, 3)
    film = {"fps": FPS, "duration": dur, "phones": {k: p.spec() for k, p in F.phones.items()}, "layout": F.layout,
            "cam": sorted(F.cam, key=lambda c: c[0]), "panel": F.panel, "persona": F.persona, "flow": F.flow,
            "flowNodes": FLOW_NODES, "cards": F.cards, "items": F.items, "focus": F.focus}
    validate(film)
    BUILD.mkdir(exist_ok=True)
    (BUILD / "film.json").write_text(json.dumps(film, ensure_ascii=False))
    timeline = {"duration": dur, "lines": F.lines, "chapters": [{"id": c, "t": round(t, 3)} for c, t in F.chapters],
                "sfx": sorted(F.sfx, key=lambda s: s["t"])}
    (BUILD / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1))
    print(f"film: {dur / 60:.2f} min, {len(F.lines)} lines, {len(F.phones)} phone views, {len(F.sfx)} sound cues")
    for c, t in F.chapters:
        print(f"  {int(t) // 60}:{int(t) % 60:02d}  {c}")


if __name__ == "__main__":
    build()
