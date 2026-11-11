# Purchase Approval Bot (WhatsApp)

A WhatsApp bot that runs site purchases for a multi-site construction company and makes leakage visible:

1. **Site requirements** (Nicobar, Kamorta, Diglipur) keep coming into the *Kailash Material* group as text, **voice notes in Hindi**, or **photos of handwritten lists**. Abbas forwards each one to the bot, or engineers message the bot directly. The bot turns it into a clean, numbered requirement for the right site.
2. **Logistics (Abbas)** sees every open item, sorted by site, and says (usually by voice) **which shop** each item comes from, with no prices: *"N17 N18 Om Traders, N19 nahi mila, N20 already sent"*. Items not available stay pending with the reason; items already sent or not needed are closed and the site is told.
3. **The approver** gets the **purchase list** on WhatsApp as a PDF plus a summary: per site, each item's shop and the **last rate paid** (from recorded bills and Zoho Books), an estimated value, and alerts. He replies **"haan"**, **"no"**, or **"3 nahi"**, or taps a button.
4. On approval the bot issues the signed list and **one signed challan per shop** (no prices) with **his name, initials stamp, verification code and QR code**. Shops supply on credit only against their challan; the QR shows whether it is genuine, already billed or expired.
5. After buying, Abbas sends a **photo of the shop's bill**. The bot reads it, checks it against the challan (items not approved, more than approved, rate above last time, total not adding up), and after Abbas confirms sends it to the approver and accounts. The billed rates become the next "last rate".
6. Everything is filed in **Google Drive** and logged in a **Google Sheet** (Purchase Register, Bills, Requisitions, Stock Ledger, Stock Summary, Audit Log).
7. When Abbas forwards his dispatch post (photo of the list + "handed over to Prem in ship" / "loaded in Anand Bus"), the bot reads every item and asks the site to confirm what arrived with one tap. Shortages go straight to Abbas and Dad. **Site stock** updates from what actually arrived.

```mermaid
flowchart LR
  E[Engineer<br/>text / voice / photo] -->|✅ Confirm| R[Requirement<br/>REQ-NIC-0012<br/>items N17, N18]
  R --> A[Abbas<br/>'N17 Om se, N18 nahi mila']
  A -->|📤 Send| S[List PS-0042<br/>shop + last rate + alerts]
  S --> F{Approver<br/>yes · no · 3 nahi}
  F -->|question| A
  F -->|approved| P[Signed list +<br/>one challan per shop]
  P --> B[Shop bill photo<br/>checked vs challan]
  B --> O[Approver + accounts]
  B --> D[Drive + Sheets]
  P --> A2[Abbas dispatches]
  A2 --> G[Engineer: All received / short]
  G --> K[Site stock]
```

See [`docs/samples/`](docs/samples) for real output from the scripted demo: a pending purchase list, a signed partly-approved list, a shop's signed challan, the requirement list, and the full WhatsApp conversation (including a shop bill checked against its challan).

## What stops leakage

| Leak | Control in the bot |
|---|---|
| Buying things no site asked for | Lines without a site requirement are flagged **"Not requested by any site engineer"** |
| Buying more than asked | **"Buying 60 bag; site asked for 50"** |
| Inflated rates | The approver sees the last rate paid for every item (bills + Zoho Books), and each shop bill is checked: **"Rate ₹450 is 12% above last ₹400 (Om Traders, 01 Sep)"** |
| Billing for things not approved | Each shop bill is matched to its signed challan: **"Not on challan PS-0042-1 — was not approved"**, **"Billed 60 bag; approved 50 bag"** |
| Supplying against an old or copied approval | Challans are per shop, signed, valid 7 days, and show **"already billed"** on the QR page once billed |
| New or friendly vendors | Vendors not on the approved list are flagged **"New vendor"** |
| Buying the same thing twice | **"Already bought 40 bag for Nicobar on 10 Oct (PS-0001)"** |
| Requirements invented at the office | Requirements Abbas types on a site's behalf are marked and flagged |
| Edited or forged slips | Ed25519 signature over the exact approved contents. The QR code opens a page that shows **INVALID** if anything was changed |
| Material that never reaches site | The engineer confirms receipt. Shortages are sent to logistics **and the approver** at once |
| "He said yes on the phone" | Only the approver's WhatsApp number can approve. Every reply is stored with its message ID in the audit log |
| Approving an outdated version | Each slip has a version. Approving an old message after Abbas changed the slip does nothing |

**Approvals are never decided by AI.** Claude only reads messy lists and notes. Approval replies are read by fixed rules ([`approval.py`](src/purchasebot/approval.py)), and anything unclear is asked again or forwarded to Abbas as a question. Voice-note approvals and 👍 reactions always need a confirm tap.

## The "Kailash Material" group stays as it is

The group keeps running the company exactly as it does now. The AI works alongside it as a **silent clerk**: it never posts in the group, reads what it is given, keeps the register, and messages only the people who need to act.

| Who | What they do |
|---|---|
| Engineers, supervisors | **Nothing new.** They keep posting requirements in the group (text, photos, voice notes). When the Purchase Desk messages them about a dispatch, they tap **✅ All received**. If they forget, they get one reminder after 2 days. |
| Abbas | Once or twice a day he selects the new requirement posts in the group and **forwards them all at once** to the Purchase Desk. The bot logs each one under the right site and sends **one summary**. Any message that doesn't name a site gets three site buttons; chat and reminders are skipped. He forwards his own dispatch posts the same way. Prices go in his chat with the bot (`N12 Om Traders 420`). Each morning he gets **today's list**: what each site is waiting for, how long, and what's approved but not sent. |
| Dad | Priced slips with alerts arrive in his chat with the Purchase Desk. He replies as he does in the group ("haan", "Abbas do it", "3 nahi"). Each evening he gets a **site-by-site summary**: what's waiting, what's in transit, shortages, spend. |

What the AI does with it:
- reads messy posts, Hindi voice notes and handwritten-list photos into clean items for the right site
- checks every price against past purchases and flags new vendors, extra quantities and repeat buys
- matches dispatches to approved items, counts what actually arrived, and keeps site stock
- keeps the Google Sheet and Drive folder up to date
- tells each person only what they need to act on

**Why can't the bot just sit in the group?** The official WhatsApp API can't join an existing group:
- Meta's Groups API only covers groups the business number itself creates, up to 8 people, joined by invite link, and only for Official Business Accounts.
- Business-app "coexistence" numbers don't pass group messages to the API either.

A bot inside the group would have to be an unofficial "WhatsApp Web" client on a spare number. That breaks WhatsApp's terms, so the number can be banned without warning. It would also log every member's messages and phone number, so everyone in the group should be told first. It is not built. If you want it, it can be added later as a read-only extra that removes Abbas's forwarding; nothing else in this design would change.

Two more WhatsApp rules:
- **The bot needs its own phone number** (a new SIM). Save it as "Purchase Desk" in everyone's phone.
- **24-hour rule:** if someone hasn't messaged the bot in 24 hours, Meta only allows a pre-approved template. The bot sends a short "needs your attention" template, and one tap brings up the full slip. You submit that template in Meta once ([setup step 2](docs/SETUP.md)).

**WhatsApp, not Slack.** The bot provides the structure (numbering, segregation, approval, filing), which is the only real advantage Slack would bring. Slack's free plan also hides messages older than 90 days, which is bad for an audit trail.

## Try it now (no WhatsApp needed)

Open [`docs/trial.html`](docs/trial.html) in a browser for a guided, clickable trial run: the group, Abbas's chat, Dad's chat and each engineer's chat side by side, with the register, slips, dispatches and stock updating live.

```bash
pip install -e '.[dev]'
purchasebot demo            # scripted run: 3 sites → slip → question → partial approval → delivery → stock
purchasebot simulate        # chat as anyone:  @abbas fwd: Diglipur site requirements -- welding goggles 10 nos   @father ^ yes
pytest                      # 97 tests
```

Without `ANTHROPIC_API_KEY`, the demo and simulator use a simple offline parser that understands lines like *"cement 50 bags"*. With the key, Claude reads Hinglish, abbreviations, voice transcripts and photos.

## Going live

[`docs/SETUP.md`](docs/SETUP.md) walks through each step: the WhatsApp number and Meta app, the server (one small VPS with Docker; HTTPS is automatic), Google Drive/Sheets, and API keys. Allow about half a day, most of it waiting on Meta.

[`docs/USAGE_GUIDE.md`](docs/USAGE_GUIDE.md) is a one-page guide per person, in English and Hindi. Use it as the script for the training videos.

**Running cost (approximate):** server ₹500–800/month. WhatsApp: a few rupees a day at this volume, since only business-initiated templates are charged (check Meta's current India rate card). Claude: well under ₹1 per requirement or slip read. Sarvam: paise per voice note.

## Project layout

```
src/purchasebot/
  workflow.py     the whole flow: requirements, slips, approvals, dispatch, delivery, stock, reminders
  approval.py     rule-based reading of "yes / no / 3 nahi / only 1 2"
  llm.py          Claude extraction (structured JSON) + offline fallback parser
  speech.py       Sarvam speech-to-text for voice notes (splits long notes with ffmpeg)
  whatsapp.py     WhatsApp Cloud API client, webhook parsing, signature check
  pdf.py          purchase list, per-shop challan and requirement list PDFs
  rates.py        last-rate lookup (strict on sizes) over bills, Zoho Books and quoted rates
  zoho.py         read-only Zoho Books sync of bill and item rates
  signing.py      Ed25519 signature + verification code
  google_sync.py  Drive uploads and Sheets upserts through a retrying queue
  app.py          webhook endpoint, /verify page, health check, scheduler
  db.py store.py  SQLite (source of truth; Sheets is a mirror)
config/roster.example.yaml   sites, people, phone numbers, vendors
```

## Worth adding next

1. **Challans to shops on WhatsApp.** Send each shop its signed challan directly, so it arrives before Abbas does. Needs each shop's number and a second Meta template.
2. **Draft bills into Zoho Books.** Create the vendor bill in Zoho from the recorded photo, so accounts only check it instead of typing it.
3. **Weekly stock count.** Every Saturday the bot asks each engineer to count 5–10 key items. Differences from the ledger show consumption that was never reported, or theft.
4. **Approval limits.** Slips under, say, ₹5,000 could be approved by a deputy, so your father only sees the big ones. This is not built in because it invites splitting large purchases into small slips. Turn it on only with a daily cap.
5. **Accounting.** Past rates are read from Zoho Books (`bash scripts/configure.sh` connects it; choose the construction company's organisation).
