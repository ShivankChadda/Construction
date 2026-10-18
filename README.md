# Purchase Approval Bot (WhatsApp)

A WhatsApp bot that runs site purchases for a multi-site construction company and makes leakage visible:

1. **Site engineers** (Nicobar, Kamorta, Diglipur) send their material list on WhatsApp as text, a **voice note in Hindi**, or a **photo of a handwritten list**. The bot turns it into a clean, numbered requirement and the engineer taps ✅ to send it.
2. **Logistics (Abbas)** sees every open item, sorted by site, and writes a purchase note the way he already does: *"N17 N18 Om Traders 420, K4 Hira Metals 62/kg"*. The bot builds a **purchase slip** and checks every line against past purchases.
3. **The approver** gets the slip on WhatsApp as a PDF plus a short summary with alerts. He replies **"haan"**, **"no"**, or **"3 nahi"**, or taps a button. Only then does the bot issue the final slip with **his name, initials stamp, timestamp, verification code and QR code**, signed with a key only the server holds.
4. The signed slip goes to logistics and observers. It is filed in **Google Drive**, and every line is logged in a **Google Sheet** (Purchase Register, Requisitions, Stock Ledger, Stock Summary, Audit Log).
5. When Abbas marks a slip dispatched, the site engineer confirms delivery with one tap or reports a shortage. **Site stock** updates from what actually arrived.

```mermaid
flowchart LR
  E[Engineer<br/>text / voice / photo] -->|✅ Confirm| R[Requirement<br/>REQ-NIC-0012<br/>items N17, N18]
  R --> A[Abbas<br/>'N17 Om Traders 420']
  A -->|📤 Send| S[Slip PS-0042<br/>+ price / qty / vendor alerts]
  S --> F{Approver<br/>yes · no · 3 nahi}
  F -->|question| A
  F -->|approved| P[Signed PDF<br/>name · stamp · QR]
  P --> D[Drive + Sheets]
  P --> A2[Abbas buys & dispatches]
  A2 --> G[Engineer: All received / short]
  G --> K[Site stock]
```

See [`docs/samples/`](docs/samples) for real output from the scripted demo: a pending slip, a signed partly-approved slip, the requirement list, and the full WhatsApp conversation.

## What stops leakage

| Leak | Control in the bot |
|---|---|
| Buying things no site asked for | Lines without a site requirement are flagged **"Not requested by any site engineer"** |
| Buying more than asked | **"Buying 60 bag; site asked for 50"** |
| Inflated rates | Every line is compared with the last approved rate for the same item: **"Rate ₹420 is 6.3% above last ₹395 (Om Traders, 10 Oct)"** |
| New or friendly vendors | Vendors not on the approved list are flagged **"New vendor"** |
| Buying the same thing twice | **"Already bought 40 bag for Nicobar on 10 Oct (PS-0001)"** |
| Requirements invented at the office | Requirements Abbas types on a site's behalf are marked and flagged |
| Edited or forged slips | Ed25519 signature over the exact approved contents. The QR code opens a page that shows **INVALID** if anything was changed |
| Material that never reaches site | The engineer confirms receipt. Shortages are sent to logistics **and the approver** at once |
| "He said yes on the phone" | Only the approver's WhatsApp number can approve. Every reply is stored with its message ID in the audit log |
| Approving an outdated version | Each slip has a version. Approving an old message after Abbas changed the slip does nothing |

**Approvals are never decided by AI.** Claude only reads messy lists and notes. Approval replies are read by fixed rules ([`approval.py`](src/purchasebot/approval.py)), and anything unclear is asked again or forwarded to Abbas as a question. Voice-note approvals and 👍 reactions always need a confirm tap.

## WhatsApp or Slack?

**Stay on WhatsApp.** The bot handles the structure (numbering, segregation, approval, filing), which is the only real advantage Slack would bring. Moving five people over 50, on island connections, to a new app solves nothing the bot doesn't already solve. Slack's free plan also hides messages older than 90 days, which is the opposite of what an audit trail needs.

Two WhatsApp rules to know:
- **The bot needs its own phone number** (a new SIM is easiest). Everyone chats with that number one-to-one. Bots can't sit in normal WhatsApp groups. Meta's Groups API is limited to 8 people and to accounts with Official Business status. One-to-one is better anyway: every message is tied to a person and a site.
- **24-hour rule:** if someone hasn't messaged the bot in 24 hours, Meta only allows a pre-approved template. The bot handles this automatically. It sends a short "needs your attention" template, and one tap brings up the full slip. You submit that one template in Meta once ([setup step 2](docs/SETUP.md)).

Use only the official WhatsApp Cloud API. Unofficial WhatsApp-Web libraries can get the number banned, which would stop purchases mid-week.

## Try it now (no WhatsApp needed)

```bash
pip install -e '.[dev]'
purchasebot demo            # scripted run: 3 sites → slip → question → partial approval → delivery → stock
purchasebot simulate        # chat as anyone:  @chandra cement 50 bags   @abbas list   @father ^ yes
pytest                      # 85 tests
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
  pdf.py          purchase slip and requirement list PDFs
  signing.py      Ed25519 signature + verification code
  google_sync.py  Drive uploads and Sheets upserts through a retrying queue
  app.py          webhook endpoint, /verify page, health check, scheduler
  db.py store.py  SQLite (source of truth; Sheets is a mirror)
config/roster.example.yaml   sites, people, phone numbers, vendors
```

## Worth adding next

1. **Vendor bill photo check.** Abbas sends a photo of the vendor's bill. Claude reads the total, and the bot flags any bill above the approved amount for that vendor. This closes the last gap: approved ₹X, billed ₹X+Y.
2. **Purchase orders to vendors.** After approval, send each vendor its own one-page signed PO, so vendors only supply against a verified slip.
3. **Weekly stock count.** Every Saturday the bot asks each engineer to count 5–10 key items. Differences from the ledger show consumption that was never reported, or theft.
4. **Approval limits.** Slips under, say, ₹5,000 could be approved by a deputy, so your father only sees the big ones. This is not built in because it invites splitting large purchases into small slips. Turn it on only with a daily cap.
5. **Accounting.** The connected Zoho Books organisations are *The Farmers of Great Nicobar Pvt Ltd* and a personal one; none is the construction company. If the construction company's books move to Zoho, approved slips can be pushed in as Purchase Orders.
