# Setup

About half a day of work, spread over one or two days because Meta reviews the display name and the message template. Do steps 2–4 first so those reviews run while you do the rest.

## 1. Collect the details (15 minutes)

Fill in a copy of `config/roster.example.yaml` (save it as `config/roster.yaml`):

- KEC's GSTIN, if it should be printed on slips (name and address are already filled in)
- Your father's full name, initials and title (printed as the signature)
- Name and WhatsApp number of every engineer and supervisor, and their site
- Abbas's number, your father's number, and your own (as observer)
- Vendors you already buy from, with the spellings people use ("Om", "Ome")
- How people write each site in the group. If "N/C" means Nancowry/Kamorta, add `n/c` to Kamorta's aliases

## 2. The Purchase Desk number (30 minutes)

Buy a new SIM and put it in a spare phone that can receive SMS. The number must **not** be on WhatsApp already. If it is, delete that WhatsApp account first (Settings → Account → Delete account).

## 3. Meta: WhatsApp Business Platform (1 hour, then wait for review)

1. <https://business.facebook.com>: create a business portfolio in KEC's name. Use your own long-standing Facebook profile with two-factor authentication on. Don't make a separate "KEC" profile: Meta disables those, and the owner's access goes with it. Add a second admin with full control (Settings → Users → People) so one locked profile can't lock out the company.
2. **Settings → Business info → Edit**: fill in the legal name, full address with PIN code, business phone (one printed on the GST or Udyam certificate, not the new SIM), website <https://shivankchadda.github.io/kec-site/> and email. Without these Meta refuses to add a number ("your business has not met WhatsApp's policy requirements").
3. <https://developers.facebook.com> → **My Apps → Create app**. Pick the **WhatsApp** use case ("Connect with customers through WhatsApp") and link the business portfolio. Meta also creates a test number and a "Test WhatsApp Business Account"; leave them, they're useful for testing.
4. **Add the number** in business.facebook.com → **Settings → Accounts → WhatsApp accounts → + Add → Create a new WhatsApp account** (the App Dashboard's Add phone number popup failed for KEC; this route worked). Choose **Add a new number**, enter the SIM's 10 digits, verify by SMS, display name "Kailash Purchase Desk", category Professional Services. Create a **new** Messaging account for it, currency **INR**, time zone Asia/Kolkata. Meta reviews the business and the name within a day or two.
5. **Settings → Billing and payments**: add a card to that new Messaging account. Check its currency is INR first; it locks once a card is attached. Meta charges only for template messages, and this bot sends very few.
6. **Permanent token**: Settings → Users → **System users** → Add (Admin) → **Assign assets**: the app (full control) **and** the new WhatsApp account (full control) → **Generate token** with `whatsapp_business_messaging` and `whatsapp_business_management`, expiry **Never**. Save it as `WA_ACCESS_TOKEN`. Don't use the 24-hour test token.
7. Copy these into a safe note for step 6:
   - **Phone number ID** (`WA_PHONE_NUMBER_ID`): Meta's dashboard shows it only for the test number now. You get KEC's from the bot in step 6.
   - **App secret** (App settings → Basic) → `WA_APP_SECRET`
   - Make up a long random string → `WA_VERIFY_TOKEN`
8. **App settings → Basic**: Privacy policy URL <https://shivankchadda.github.io/kec-site/privacy.html>, then **Publish** (left sidebar of the app dashboard) to take the app out of development. Until it's published, real messages may not reach the bot.

KEC's own number won't send or receive anything until step 6 registers it with Meta. Until then, build and test with the test number: on the Step 1. Try it out page, add up to 5 phones under **To** and use the test number's Phone number ID.

## 4. Meta: the one message template (10 minutes, then wait for review)

WhatsApp Manager → **Message templates → Create**:

- Category: **Utility**. Name: `action_required`. Language: **English**.
- Body: `Your KEC purchase order has an update: {{1}}. Tap Show details to view the order and respond.` (Meta's check rejected vaguer wording as marketing.)
- Sample for {{1}}: `Purchase slip PS-0042 (₹1,55,000) is waiting for your approval`
- Button: **Custom** (quick reply) → `Show details`
- Validity period: turn on and pick **12 hours**. The screen says the default is 10 minutes, so a phone that's offline briefly would miss the reminder.

The bot only uses it when someone hasn't messaged the Purchase Desk for 24 hours (Meta's rule).

## 5. Server and web address (45 minutes)

1. Rent a small Linux server: AWS Lightsail (Mumbai) or DigitalOcean (Bangalore), Ubuntu 24.04, 1 vCPU / 1 GB RAM, about ₹500–800 a month.
2. In the provider's firewall, allow ports **80** and **443**.
3. Point a web address at the server's IP with a DNS **A record**, for example `purchases.yourcompany.in`. If you have no domain, a free DuckDNS name works.
4. Install Docker on the server:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```

## 6. Install the bot (30 minutes)

On the server:

```bash
git clone -b claude/construction-purchase-approval-ooqlxi https://github.com/ShivankChadda/Construction.git purchasebot
cd purchasebot
```

The repository is private, so Git asks for your GitHub username and a password. Use a GitHub **personal access token** with read access to the repository (GitHub → Settings → Developer settings → Fine-grained tokens).

Then:

```bash
bash scripts/configure.sh      # asks for the web address and keys (typed hidden), writes .env
nano config/roster.yaml        # paste the roster from step 1
docker compose run --rm bot purchasebot wa-numbers   # shows KEC's Phone number ID
bash scripts/configure.sh      # run again and enter that Phone number ID
docker compose run --rm bot purchasebot wa-register 482915   # pick your own 6 digits, once
docker compose run --rm bot purchasebot wa-subscribe MESSAGING_ACCOUNT_ID   # asset_id in WhatsApp Manager's address bar, once
docker compose up -d --build
docker compose run --rm bot purchasebot check
curl https://YOUR-DOMAIN/healthz
```

`wa-register` connects KEC's number to the Cloud API; Meta has no button for this. The 6 digits become the number's two-step verification PIN, so write them down. Run it again after Meta approves a display name change. More than 10 attempts in 3 days locks registration for 3 days.

`check` lists every person it found and which keys are still missing. Caddy gets the HTTPS certificate on its own within a minute.

**Back up two things:** the `.env` file and the `data/` folder (the database, PDFs and `signing.key`). The bot also uploads a database backup to Google Drive every day once step 8 is done. Without `signing.key`, old slips can't be verified.

## 7. Connect WhatsApp to the server (10 minutes)

developers.facebook.com → your app → **WhatsApp → Configuration → Webhook → Edit**:

- Callback URL: `https://YOUR-DOMAIN/webhook`
- Verify token: your `WA_VERIFY_TOKEN`
- Click **Verify and save**, then **subscribe to `messages`**.

## 8. Google Drive and Sheets (30 minutes)

Use the Google account that should own the files, for example the office Gmail.

1. <https://console.cloud.google.com> → create a project → **APIs & Services → Library**: enable **Google Drive API** and **Google Sheets API**.
2. **Google Auth Platform** (formerly "OAuth consent screen"):
   - **Branding**: app name "KEC Purchase Desk" and your email.
   - **Audience**: External, then **Publish app** so it shows "In production". Do this before signing in. Sign-ins made in Testing mode stop working after 7 days.
   - **Clients → Create client → Desktop app**. Note the client ID and secret.
3. On your laptop (the sign-in opens a browser):
   ```bash
   git clone -b claude/construction-purchase-approval-ooqlxi https://github.com/ShivankChadda/Construction.git && cd Construction
   pip install -e .
   GOOGLE_OAUTH_CLIENT_ID=… GOOGLE_OAUTH_CLIENT_SECRET=… purchasebot google-auth
   ```
   Google warns that the app is unverified: click **Advanced → Go to KEC Purchase Desk**. It's your own app, and it can only see files it creates. The command prints `GOOGLE_OAUTH_REFRESH_TOKEN=…`.
4. Create the folder and the Purchase Register sheet:
   ```bash
   GOOGLE_AUTH_MODE=oauth GOOGLE_OAUTH_CLIENT_ID=… GOOGLE_OAUTH_CLIENT_SECRET=… GOOGLE_OAUTH_REFRESH_TOKEN=… purchasebot google-setup
   ```
   It prints `GOOGLE_DRIVE_ROOT_FOLDER_ID` and `GOOGLE_SHEET_ID`.
5. On the server, add all five Google values to `.env`, set `GOOGLE_AUTH_MODE=oauth`, and run `docker compose up -d`.

Why not a service account? Google service accounts have no Drive storage of their own, so they can't upload PDFs into a normal Gmail Drive. They work only with a Google Workspace *shared drive*. If you have one, set `GOOGLE_AUTH_MODE=service_account` and `GOOGLE_SERVICE_ACCOUNT_FILE`, and share the shared drive with the service account.

## 9. Claude and Sarvam keys (15 minutes)

- **Claude** reads messy posts and photos: <https://console.anthropic.com> → add credits → **API keys** → `ANTHROPIC_API_KEY`.
- **Sarvam** transcribes Hindi voice notes: <https://dashboard.sarvam.ai> → API key → `SARVAM_API_KEY`.

Add both to `.env` on the server and run `docker compose up -d`. Without Claude, the bot falls back to a basic reader that understands only lines like "cement 50 bag". Without Sarvam, voice notes get a "please type it" reply.

## 10. Test run with three phones (30 minutes)

Sit with Abbas and your father, or use three phones whose numbers are in the roster.

1. Everyone sends **hi** to the Purchase Desk. Each person gets their own help message.
2. In the group, someone posts a small real requirement. Abbas forwards it to the Purchase Desk and gets the summary.
3. Abbas types `list`, then a slip line like `D1 Om Traders 180`, and taps **Send for approval**.
4. Your father replies **haan**. Check that the signed PDF reaches Abbas, then scan its QR code.
5. Abbas forwards a dispatch post. The engineer taps **All received**.
6. Open the Google Sheet and check the rows, and check that the PDF is in Drive.

## 11. Go live with the team

1. Message the group: nothing changes for them. Keep posting here; Abbas forwards to the Purchase Desk; tap "All received" when the Purchase Desk asks.
2. Everyone not yet done sends **hi** to the Purchase Desk once.
3. For the first week, check the evening summary with your father.

## Later

- **Change people or vendors**: edit `config/roster.yaml`, then `docker compose restart bot`. A person's phone number is their identity, so update it before they switch numbers.
- **Update the bot**: `git pull`, then `docker compose up -d --build`.
- **Something looks wrong**: `docker compose logs --tail 100 bot`.
