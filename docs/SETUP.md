# Setup

Allow about half a day. Most of it is waiting for Meta to approve the display name and message template.

## 1. A phone number for the bot

Buy a new SIM (any operator) and keep it in an old phone that can receive SMS. The number **must not be registered on WhatsApp**. If it is, delete that WhatsApp account first (WhatsApp → Settings → Account → Delete account).

This number becomes the "Purchase Desk" that everyone chats with. Save it in every engineer's phone under that name.

## 2. WhatsApp Cloud API (Meta)

1. Create a Meta Business account at <https://business.facebook.com> in the company's name.
2. Go to <https://developers.facebook.com> → **My Apps → Create app**. Choose type **Business**, then add the **WhatsApp** product.
3. **WhatsApp → API Setup → Add phone number.** Enter the SIM number, verify it by SMS, and set the display name (for example, "<Company> Purchase Desk").
4. **Permanent token:** business.facebook.com → Settings → Users → **System users** → Add (Admin). Then *Assign assets* → your app (full control) → **Generate token**, with permissions `whatsapp_business_messaging` and `whatsapp_business_management`. This becomes `WA_ACCESS_TOKEN`. Don't use the 24-hour test token.
5. Copy **Phone number ID** (from API Setup) → `WA_PHONE_NUMBER_ID`.
   Copy **App secret** (App settings → Basic) → `WA_APP_SECRET`.
6. Invent a random string for `WA_VERIFY_TOKEN`.
7. **Message template** (WhatsApp Manager → Message templates → Create):
   - Category: **Utility**. Name: `action_required`. Language: English.
   - Body: `Hello, there is an update that needs your attention: {{1}}. Tap the button below to see the details.`
   - Sample for {{1}}: `Purchase slip PS-0042 (₹1,55,000) is waiting for your approval`
   - Button: **Quick reply** → `Show details`

   Approval usually takes minutes to a few hours. The bot uses this template only when someone hasn't messaged it in 24 hours.
8. Do step 3 below, then come back: **WhatsApp → Configuration → Webhook**:
   - Callback URL: `https://YOUR-DOMAIN/webhook`
   - Verify token: the same `WA_VERIFY_TOKEN`
   - **Subscribe to the `messages` field.**

Business verification (uploading company documents) is optional to start. The unverified limit, about 250 people messaged per day, is far above what you need.

## 3. Server

Any small Linux VPS works, for example AWS Lightsail in Mumbai or DigitalOcean in Bangalore (1 vCPU, 1 GB, ~₹500–800/month).

```bash
# on the server
curl -fsSL https://get.docker.com | sh
git clone <this repo> purchasebot && cd purchasebot
cp config/roster.example.yaml config/roster.yaml   # fill in real names and numbers
cp .env.example .env                                # fill in keys (steps 2, 4, 5)
docker compose run --rm bot purchasebot gen-key     # paste the SIGNING_KEY line into .env
```

Point a domain or subdomain (for example `purchases.yourcompany.in`) at the server's IP with a DNS **A record**, and set `DOMAIN` and `PUBLIC_BASE_URL` in `.env`. Then:

```bash
docker compose up -d
docker compose run --rm bot purchasebot check
curl https://YOUR-DOMAIN/healthz
```

Caddy obtains the HTTPS certificate automatically.

**Back up `data/`.** It holds the database, the PDFs and `signing.key`. A database backup is also uploaded to Google Drive every day once step 4 is done. Without the signing key, old slips can no longer be verified, so keep a copy somewhere safe.

## 4. Google Drive + Sheets

Use the Google account that should own the files (for example, your father's or the office Gmail).

1. <https://console.cloud.google.com> → create a project → **APIs & Services → Library**: enable **Google Drive API** and **Google Sheets API**.
2. **OAuth consent screen:** choose External, fill in the app name and your email, then **Publish app** (set it to "In production"). In "Testing" mode, Google expires the sign-in after 7 days. The app only asks for the `drive.file` permission, which means it can see only the files it creates, not the rest of the Drive.
3. **Credentials → Create credentials → OAuth client ID → Desktop app.** Put the client ID and secret into `.env` as `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET`.
4. On a laptop with a browser (the sign-in opens a browser window):
   ```bash
   pip install -e .
   purchasebot google-auth      # sign in → prints GOOGLE_OAUTH_REFRESH_TOKEN
   purchasebot google-setup     # creates "<Company> - Purchases" folder + "Purchase Register" sheet
   ```
   Google will warn that the app is unverified. Click *Advanced → Go to app*; it's your own app.
5. Copy the printed values into the server's `.env`, set `GOOGLE_AUTH_MODE=oauth`, then run `docker compose up -d`.

Why not a service account? Google service accounts have no Drive storage of their own, so they can't upload PDFs into a normal Gmail Drive. They work only with a Google Workspace *shared drive*. If you have one, set `GOOGLE_AUTH_MODE=service_account` and `GOOGLE_SERVICE_ACCOUNT_FILE`, and share the shared drive with the service account.

## 5. API keys

- **Claude:** <https://console.anthropic.com> → API keys → `ANTHROPIC_API_KEY`. Without it, the bot falls back to a basic parser that only understands lines like "cement 50 bags".
- **Sarvam AI** (Hindi voice notes): <https://dashboard.sarvam.ai> → `SARVAM_API_KEY`. Without it, voice notes get a polite "please type it" reply.

## 6. First day

1. Ask each person to send **hi** to the bot number. They get their own help message, and this also opens the 24-hour window.
2. Run one real requirement end to end with Abbas sitting next to you.
3. Open the Google Sheet and check the rows.
4. Scan the QR code on the first signed slip with a phone.

## Changing people or vendors

Edit `config/roster.yaml`, then run `docker compose restart bot`. A person's phone number is their identity. If someone changes numbers, update it here before they use the new one.
