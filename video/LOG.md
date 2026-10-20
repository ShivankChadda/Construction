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
  like with like (youtube repo L25, L255). On screen every step is in both Hindi (Devanagari) and English. Subtitles in
  both (`.hi.srt` as spoken, `.en.srt` the meaning). Bot messages stay exactly as the bot writes them (English, with the
  Hinglish replies people type).
- **Voice:** ElevenLabs `KWuQEGxZQtpWhRutt6g6` (eleven_multilingual_v2, speed 1.0), the voice the user chose for Hinglish
  (youtube repo, film 29, 15 Oct 2026). Each line voiced on its own. 59 lines, 9.1 min of speech, 154 words a minute.
- **Names in the narration:** "अब्बास जी", "चड्ढा साहब" (respectful, and what the team says), and "आप" in his own chapter.
  In the others' phones he is saved as "Chadda Sahab"; the bot prints his full name.
- **Chapters** (each person can be sent only their part): 0:00 opening (what it is, the group stays the same, the flow,
  save the number and send "hi"), 1:25 site engineers, 3:37 Abbas, 6:57 Mr Chadda, 9:40 the whole journey (three phones
  side by side, the slip travelling between them). Three personal versions: opening + their chapter + the journey.
- **Picture:** an Android-WhatsApp-style phone (light theme, green header, real bubbles, buttons, forwarded labels,
  quoted replies, PDF previews, voice notes, photos, selection mode, the Forward picker, the PDF viewer, notification
  banners), built in HTML/CSS and drawn frame by frame from the time alone (`web/engine.js`). No WhatsApp logo or sound
  is used. Beside the phone, a step panel in Hindi and English, the person's name and role, and a five-step flow strip.
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

## Deliveries

| # | Date | Cut | Where | QC |
|---|---|---|---|---|

## Feedback rounds

| # | Date | The user said (verbatim) | What was wrong | Fix and commit |
|---|---|---|---|---|

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
