# Log: Purchase Desk tutorial video (Hinglish)

Folder `video/` of the Construction repo · started 2026-10-20 · branch `claude/purchase-desk-tutorial-video`. Built with
the youtube repo's methods (its Hindi web engine from film 07, its Hinglish voice from film 29, its speech check and quality
gate), but it is a training film for the company, not a YouTube channel film, so it lives next to the bot it explains.

## Brief (the user's words, verbatim)

> We have created a construction purchase approval workflow. What I want you to do is create a tutorial video explaining
> how it is going to work. You should be inspired by the actual WhatsApp interface on a phone.
>
> It's going to be an explanation for Abbas, my father, other engineers, and everyone. You have to show the entire
> end-to-end workflow from my father's perspective, from my engineer's perspective, and from Abbas's perspective. Have
> different chapters on it. It should be in Hinglish, Hindi and English both

Asked before building (20 Oct 2026):
- The approver's name on screen and on the signed slip: **"Munishwer chander chadda"** (printed as Munishwer Chander
  Chadda, initials MCC). The roster's placeholder was "Father's Full Name".
- Shape: **landscape 16:9** (the recommendation was vertical 9:16 for phones; the user chose landscape).

## Decisions

- **Every WhatsApp message is the bot's own output.** `capture.py` runs `src/purchasebot` through one story with a roster
  carrying the real names (`roster.yaml`): three sites post in the group, Abbas forwards four posts at once (text, a
  Hindi voice note, a photo of a handwritten list, an "ok sir"), one needs a site button, he lists, prices a slip
  (four alerts: rate 6.3% up twice, cement already bought on 12 Oct, new vendor), Mr Chadda asks "cement 420 kyun?",
  Abbas answers, Mr Chadda replies "5 nahi" and confirms, the signed slip goes out, Abbas dispatches (a forwarded group
  post and a typed command), Siddhu taps All received, Chandramohan is reminded after 48 h and reports 2 of 3 trucks of
  sand. The PDFs on screen are the bot's PDFs. Only the reading of the voice note and the photo is scripted (they need
  Claude in real use); everything after that is the bot's code.
- **Chat order follows the bot.** The story was ordered so each phone's chat reads top to bottom in the order the
  narration shows it (the dispatch post is forwarded before the typed dispatch; Mr Chadda types his question without
  quoting, since one slip is waiting).
- **Language:** narration in Hinglish (Hindi sentences with the English words people use: slip, approve, forward,
  button), written all in Devanagari so the voice says it as a Hindi speaker does and the Hindi speech check compares
  like with like (youtube repo L25, L255). **The screen is in English** (feedback round 1): every step, label, card,
  heading and name tag. Subtitles in English (`.en.srt`, the meaning of the narration). Bot messages stay exactly as
  the bot writes them (English, with the Hinglish replies people type); the one exception is the bot quoting a Hindi
  voice note back in Hindi script, which is what Sarvam's `saaras:v4` returns (its docs show Devanagari output in the
  default mode), so Abbas sees on screen what he will see on his phone.
- **Voice:** ElevenLabs `KWuQEGxZQtpWhRutt6g6` (eleven_multilingual_v2, speed 1.0), the voice the user chose for Hinglish
  (youtube repo, film 29, 15 Oct 2026). Each line voiced on its own. 59 lines, 9.1 min of speech, 154 words a minute.
- **Names in the narration:** "अब्बास जी", "चड्ढा साहब" (respectful, and what the team says), and "आप" in his own chapter.
  In the others' phones he is saved as "Chadda Sahab"; the bot prints his full name.
- **Chapters** (each person can be sent only their part): 0:00 opening (what it is, the group stays the same, the flow,
  save the number and send "hi"), 1:26 site engineers, 3:41 Abbas, 7:05 Mr Chadda, 9:59 the whole journey (three phones
  side by side, the slip travelling between them). Three personal versions: opening + their chapter + the journey.
- **Picture:** an Android-WhatsApp-style phone (light theme, green header, real bubbles, buttons, forwarded labels,
  quoted replies, PDF previews, voice notes, photos, selection mode, the Forward picker, the PDF viewer, notification
  banners), built in HTML/CSS and drawn frame by frame from the time alone (`web/engine.js`). No WhatsApp logo or sound
  is used. Beside the phone, a step panel in English, the person's name and role, and a five-step flow strip.
  The camera moves in to read a message (text 30-40 px on a 1080 frame, readable on a phone held sideways) and the
  panel steps aside while it does.
- **Sound:** narration at -14 LUFS; soft synthesised UI sounds (message, send, tap, notification, chapter whoosh) and a
  quiet chord bed above 170 Hz (so a phone speaker plays it), ducked under speech; effects and bed 28 LU under the
  voice (rule: at least 18).

## Checks

- Speech check (`youtube-/tools/asr_check.py`, Sarvam read-back): 59 sentences, median CER 0.004; the one FAIL is the
  check writing "थ्री डैश टू" as the digits "3-2" (the voice says it right); WARNs are spellings (पर्चेज़/परचेस). Line e7's
  first take said "ऑन रिसीव्ड" for "ऑल रिसीव्ड"; take 2 is used (`narrate.SEEDS`).
- `storyboard.py` validates that every tap, scroll, ring and camera move points at a message that is on screen.
- Stills reviewed for every beat (contact sheets); fixed: photo bubbles, float overflow in voice notes, a heading over
  the phone name tags (two-phone shot), the slip zoom scrolled away by later messages (the chat now stays where you
  scrolled until you send, as WhatsApp does), a command box running off the frame, the journey's moving labels over the
  phones.

- **Fact audit** (an independent agent, every line against `src/purchasebot` and the capture): 0 wrong, 10 overstated,
  49 supported. Nine lines reworded and re-voiced (speech check PASS, 0 WARN):
  - i2: the bot tells each person about their own part (engineers also get FYI messages that need no action);
  - i5: "hi" brings a help message of commands, not a to-do list;
  - e2: the site is found from the message or the photo's caption; without it Abbas picks it with a tap;
  - a14: a signed slip comes only on approval, full or part (a rejected slip is not signed);
  - a19: the morning list comes when something is open;
  - m3: the alerts exactly as coded: rate more than 5% up, new shop, more than asked, same site within 10 days,
    nobody asked for it;
  - m10: the QR shows the slip as approved on the server; a changed paper is caught by comparing it with that page
    (the scan does not itself fail);
  - m14: "report" is this month's spending;
  - j4: Drive and Sheet filing work once Google is connected (off until set up).
  - Not in the narration, for the user: the signed PDF itself prints "Any change to items, quantities, rates or vendors
    makes the check fail" (`src/purchasebot/pdf.py`), the same overstatement as m10's first wording.
  - a4 (the bot reads voice notes and photos) holds only with the Claude and Sarvam keys set, as the README plans.
- **Text on text:** `web/render.mjs --textcheck` now counts only text that can be seen (topmost opaque layer at its
  centre; clipping honoured). First pass 305 frames: chat text scrolling behind the input bar, chapter cards
  cross-fading over phone text, the notification banner fading over the header, the parts list fading in over phones,
  the first phone fading in under the title. Fixed (the chat ends above the input bar as in WhatsApp; cards cut in and
  slide away, opaque; the banner slides, never fades; timings). Second pass: 1 frame (2:04), a chat screen sliding over
  another, checked by eye: clean.

## Deliveries

| # | Date | Cut | Where | QC |
|---|---|---|---|---|
| 1 | 10-20 04:30 | full film 10:46; site engineers 4:16, Abbas 5:26, Mr Chadda 4:55; Hindi + English subtitles | Drive `Kailash Construction/Purchase Desk tutorial/` ([folder](https://drive.google.com/drive/folders/1QY9kkkLSsY3T4PzdAWtncxBcbwHb4Ytu), [full film](https://drive.google.com/file/d/17qEWKqO-WovI-hIXPST5JATc000hrljl/view), [engineers](https://drive.google.com/file/d/1jA_KfyDP7ODve2StXZaxWwEFfZaFsOma/view), [Abbas](https://drive.google.com/file/d/1AWW6Kosu8L3IMNKcID3p9AQJgqIjKYd_/view), [Mr Chadda](https://drive.google.com/file/d/1q_FBnsvJYsO6AYredIcQCoJT0bD12SPI/view)), MD5 verified | `qc.py` PASS: h264 1920x1080 30 fps, -14.0 LUFS, -1.7 dBTP, no black, no silence, 5 chapters. WARN: 33 holds of 5-10 s where the phone sits still while the voice explains (intended: time to read); no thumbnail (not a YouTube upload) |
| 2 | 10-20 | round 1 fix: English on screen, English subtitles only; same lengths (10:46, 4:16, 5:26, 4:55) | Drive, same files and links (previous versions in `Old versions/`; the Hindi subtitles moved there too), MD5 verified | `qc.py` PASS on all four (full film -14.0 LUFS, -1.7 dBTP, 5 chapters; cuts -13.9 to -14.3 LUFS, -1.8 dBTP); no Devanagari in `film.json` outside the bot's own voice-note quote; text check 1 known frame |


## Feedback rounds

| # | Date | The user said (verbatim) | What was wrong | Fix and commit |
|---|---|---|---|---|
| 1 | 10-20 | "The text shouldn't be in Hindi. Keep it in English." | One kind of fault, 136 places: every on-screen string outside the WhatsApp messages carried Hindi (Devanagari): 91 step-panel lines, 17 headings, labels and the parts list, 10 phone name tags, 8 chapter-card lines, 5 role lines, 5 flow-strip labels; plus the Hindi subtitle files. The brief's "Hinglish, Hindi and English both" was read as bilingual text; it meant the voice. | All 136 rewritten in English (panel headline + English detail; cards, tags, flow strip, parts list, end card); fonts set to Roboto; Hindi subtitles dropped (moved into Drive's `Old versions/`, not deleted). The narration is unchanged. `storyboard.validate()` now fails on any Devanagari in `film.json` outside a bot message (`screen_text_is_english`, tested with a planted string). Text check: 1 frame (the known chat slide at 2:04, clean by eye). Re-rendered, qc PASS. |

## Rebuild

```bash
python3 video/capture.py      # the bot's messages and PDFs (offline, nothing is sent)
python3 video/narrate.py      # ElevenLabs narration (cached; only changed lines cost credits)
python3 video/storyboard.py   # build/film.json + timeline.json
python3 video/mix.py          # build/mix.wav
cd video/web && npm install && cd ../..
node video/web/render.mjs --textcheck --step 0.25
node video/web/render.mjs --video --jobs 4
python3 video/deliver.py      # output/: full film, three personal versions, Hindi and English subtitles
```
