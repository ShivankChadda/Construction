# How to use the Purchase Desk — उपयोग गाइड

Save the bot's number as **Purchase Desk**. Send **hi** at any time to see your own help message.
बॉट का नंबर **Purchase Desk** नाम से सेव करें। कभी भी **hi** भेजें — आपकी मदद का मैसेज आ जाएगा।

---

## Site engineers — साइट इंजीनियर

**1. Send the material list — सामान की लिस्ट भेजें**
- Type it: `Cement 50 bag, sariya 12mm 2 ton, balu 3 truck`
- or send a 🎙 **voice note**: *"Nicobar ke liye pachaas bag cement aur do ton sariya baarah mm chahiye"*
- or send a 📷 **photo** of the written list.

लिख कर, बोल कर (वॉइस नोट) या लिस्ट की फोटो भेजें — तीनों चलेंगे।

**2. Check and confirm — जाँच कर Confirm दबाएँ**
The bot sends the list back with numbers. If it's right, tap **✅ Confirm**.
To change it, just send the change: `cement 60 bag`, `sand hatao` (remove sand).
बॉट लिस्ट वापस भेजेगा। सही है तो **✅ Confirm** दबाएँ। बदलना है तो बस बदलाव लिख दें।

You get a number like **REQ-NIC-0012**. Each item gets a code like **N17**. Use these codes when talking to Abbas.

**3. When material arrives — माल आने पर**
You'll get a 🚚 message. Tap **✅ All received** if everything came.
If something is short or damaged, tap **⚠️ Short/damaged** and write what came, e.g. `1-45, 3-0` (line 1: 45 came, line 3: nothing came).
सब आ गया तो **All received**। कम आया तो **Short/damaged** दबा कर लिखें क्या आया।

**Other commands — और कमांड**
- `stock` — site stock (साइट का स्टॉक)
- `used 10 bag cement` — record what was used (खर्च दर्ज करें)
- `status` — your open requirements
- `received` — deliveries still due

---

## Abbas — logistics

- `list` — all open requirements from all sites, sorted by site, with a PDF to take to the market.
- **Make a slip:** one line per vendor and rate:
  ```
  N17 N18 Om Traders 420
  N19 Hira Metals 62 per kg
  K4 Om Traders 1450
  freight Nicobar 4500 lump sum MV Swaraj Dweep
  ```
  The bot shows the slip with any alerts (higher rate, new vendor, more than asked). Send changes as normal messages, then tap **📤 Send for approval**.
- When the approver asks something, the question comes to you. **Reply to that message** (swipe right) and your answer goes back to him.
- `edit PS-42` — pull a slip back to change it. The old copy can no longer be approved.
- After approval, buy **only** what the signed slip says, from the vendor it names.
- `dispatch PS-42 Nicobar MV Campbell Bay` — tells the site the material is on its way.
- `Nicobar: cement 50 bag` — enter a requirement for a site whose engineer called you. It is marked as entered by you.
- `slips` — recent slips. `stock` — stock at all sites.

---

## Approver — मंज़ूरी देने वाले

Each slip comes as a **PDF + a summary + buttons**. Lines with ⚠️ need a look: price higher than last time, new vendor, more than the site asked for, or bought recently.
हर स्लिप PDF और सारांश के साथ आएगी। ⚠️ वाली लाइन ध्यान से देखें।

**Reply to the slip — स्लिप के मैसेज पर जवाब दें:**

| You send — आप भेजें | Result — नतीजा |
|---|---|
| **haan** / **yes** / **ok** / 👍 / tap ✅ | Everything approved — सब मंज़ूर |
| **nahi** / **no** / tap ❌ | Everything rejected — सब नामंज़ूर |
| **3 nahi** | All approved except line 3 — लाइन 3 छोड़ कर सब मंज़ूर |
| **only 1 2** / **sirf 1 2** | Only lines 1 and 2 approved — सिर्फ 1 और 2 |
| Anything else, e.g. *"cement 420 kyun?"* | Sent to Abbas as your question; the slip keeps waiting — अब्बास को सवाल चला जाएगा |

- For a partial approval (some lines only), the bot asks you to tap **Confirm** once.
- A 🎙 voice reply also works. The bot shows what it heard and asks you to tap **Confirm**.
- If several slips are waiting, **reply on the slip's own message** (swipe right on it), or write e.g. `yes PS-42`.
- `pending` — slips waiting for you. `report` — this month's spending by site and vendor.

When you approve, the final slip is issued with **your name, initials stamp, date and a verification code**. Without your "yes", no slip carries your name.
आपकी "हाँ" के बिना किसी स्लिप पर आपका नाम नहीं आता।

---

## Video script outline (Hindi, 2–3 minutes per person)

1. Save the number and send "hi" (show the help reply).
2. Engineer: send one voice note, check the list, tap Confirm.
3. Abbas: type `list`, write two slip lines, tap Send.
4. Approver: open the PDF, reply "haan" on the slip, then show the signed PDF.
5. Engineer: tap "All received" on the dispatch message.
