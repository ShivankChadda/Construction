"""The tutorial's narration: Hinglish, spoken by one ElevenLabs voice (the one the user chose for Hinglish,
KWuQEGxZQtpWhRutt6g6). Each line: (id, Devanagari as spoken, English meaning).

The spoken text is all Devanagari, the English words too ("स्लिप", "ऑल रिसीव्ड"), as the Hindi films in the
youtube repo are written, so the voice says them as a Hindi speaker does and the Hindi speech check compares like
with like. Numbers and codes are written as they are said. The English column is the meaning, used for the English
subtitles; the screen shows the exact WhatsApp text.

Every claim was checked against the bot's code (video/FACTS.md).
"""

CHAPTERS = [
    # id, Hindi title, English title, who
    ("intro", "पर्चेज़ डेस्क क्या है?", "What is the Purchase Desk?", ""),
    ("engineer", "साइट इंजीनियर", "Site engineers", "Chandramohan · Nicobar"),
    ("abbas", "अब्बास जी · लॉजिस्टिक्स", "Abbas · Logistics", "Abbas"),
    ("md", "चड्ढा साहब · अप्रूवल", "Mr Chadda · Approval", "Munishwer Chander Chadda"),
    ("journey", "पूरा सफ़र", "The whole journey", ""),
]

LINES = [
    # ---------------------------------------------------------------- intro
    ("intro", "i1", "नमस्ते। यह वीडियो हमारे नए पर्चेज़ डेस्क के बारे में है। पर्चेज़ डेस्क एक व्हाट्सऐप नंबर है, जो साइट "
     "की हर ज़रूरत, हर पर्चेज़ स्लिप और हर अप्रूवल का हिसाब रखता है।",
     "Namaste. This video is about our new Purchase Desk: a WhatsApp number that keeps track of every site "
     "requirement, every purchase slip and every approval."),
    ("intro", "i2", "सबसे पहली बात: कैलाश मटीरियल ग्रुप वैसे ही चलेगा, जैसे अभी चलता है। पर्चेज़ डेस्क ग्रुप में कुछ "
     "नहीं लिखता। वह एक क्लर्क की तरह चुपचाप हिसाब रखता है, और हर किसी को सिर्फ़ उसके अपने काम की बात भेजता है।",
     "First: the Kailash Material group keeps running exactly as it does now. The Purchase Desk never posts in the "
     "group. Like a silent clerk it keeps the books, and tells each person only about their own part of the work."),
    ("intro", "i3", "काम तीन लोगों के बीच चलता है। साइट इंजीनियर ज़रूरत बताते हैं। अब्बास जी रेट लगाकर पर्चेज़ स्लिप "
     "बनाते हैं। और चड्ढा साहब स्लिप अप्रूव करते हैं।",
     "The work moves between three people. Site engineers say what they need. Abbas prices it into a purchase slip. "
     "And Mr Chadda approves the slip."),
    ("intro", "i4", "अप्रूवल के बाद अब्बास जी सिर्फ़ वही सामान ख़रीदते हैं जो स्लिप पर मंज़ूर है, और उसे साइट भेजते हैं। "
     "साइट बटन दबाकर बताती है कि क्या पहुँचा, और उसी से साइट का स्टॉक बनता है।",
     "After approval Abbas buys only what the slip approves, and sends it to site. The site taps a button to say "
     "what arrived, and that is what goes into the site's stock."),
    ("intro", "i5", "शुरू करने के लिए, पर्चेज़ डेस्क का नंबर अपने फ़ोन में पर्चेज़ डेस्क नाम से सेव कीजिए, और उसे हाय "
     "भेजिए। आपकी अपनी मदद का मैसेज आ जाएगा: क्या लिखना है, और क्या दबाना है।",
     "To start, save the Purchase Desk number in your phone as \"Purchase Desk\" and send it \"hi\". Your own "
     "help message comes back: what to type and what to tap."),
    ("intro", "i6", "इस वीडियो के तीन हिस्से हैं: पहले साइट इंजीनियर, फिर अब्बास जी, और फिर चड्ढा साहब। आख़िर में पूरा "
     "सफ़र एक साथ।",
     "This video has three parts: site engineers first, then Abbas, then Mr Chadda. At the end, the whole journey "
     "together."),

    # ---------------------------------------------------------------- site engineers
    ("engineer", "e1", "साइट इंजीनियर के लिए अच्छी ख़बर: आपको कुछ नया नहीं सीखना। ज़रूरत पहले की तरह ग्रुप में डालिए। "
     "लिखकर, वॉइस नोट में बोलकर, या लिस्ट की फ़ोटो खींचकर।",
     "Good news for site engineers: there's nothing new to learn. Post your requirement in the group as before: "
     "typed, as a voice note, or as a photo of the list."),
    ("engineer", "e2", "बस मैसेज में, या फ़ोटो के कैप्शन में, साइट का नाम लिख दीजिए, जैसे कार निकोबार, कमोर्टा या "
     "डिगलीपुर। नाम न हो, तो अब्बास जी को बटन दबाकर साइट चुननी पड़ती है।",
     "Just write the site's name in the message, or in the photo's caption, like Car Nicobar, Kamorta or Diglipur. "
     "Without it, Abbas has to pick the site with a tap."),
    ("engineer", "e3", "दिन में एक-दो बार अब्बास जी ग्रुप के ये मैसेज पर्चेज़ डेस्क को भेजते हैं। आपकी ज़रूरत दर्ज होते "
     "ही, पर्चेज़ डेस्क आपको यह मैसेज भेजता है।",
     "Once or twice a day Abbas sends these group posts to the Purchase Desk. As soon as your requirement is "
     "logged, the Purchase Desk sends you this message."),
    ("engineer", "e4", "हर चीज़ को एक नंबर मिलता है। एन फ़ॉर निकोबार, के फ़ॉर कमोर्टा, और डी फ़ॉर डिगलीपुर। कुछ ग़लत "
     "दिखे, तो अब्बास जी को बता दीजिए।",
     "Every item gets a number: N for Nicobar, K for Kamorta, D for Diglipur. If anything looks wrong, tell Abbas."),
    ("engineer", "e5", "स्लिप पर फ़ैसला होते ही आपको पता चल जाता है कि आपकी कौन सी चीज़ ख़रीदी जाएगी, और कौन सी नहीं।",
     "As soon as the slip is decided, you learn which of your items will be bought, and which won't."),
    ("engineer", "e6", "अब आपका इकलौता नया काम। सामान भेजा जाता है, तो पर्चेज़ डेस्क आपको लिस्ट भेजता है: क्या गया, और "
     "किस जहाज़ या बस से।",
     "Now your one new job. When material is sent, the Purchase Desk sends you the list: what was sent, and on "
     "which ship or bus."),
    ("engineer", "e7", "सामान पहुँचे, तो गिनिए। सब पूरा आया, तो ऑल रिसीव्ड दबाइए। बस इतना ही।",
     "When it arrives, count it. If everything came, tap All received. That's all."),
    ("engineer", "e8", "कुछ कम आया, या टूटा हुआ आया, तो शॉर्ट या डैमेज्ड दबाइए, और लिखिए कि असल में क्या आया।",
     "If something is short or damaged, tap Short/damaged and write what actually came."),
    ("engineer", "e9", "जैसे यहाँ रेत के तीन ट्रक में से दो ही आए। लाइन तीन में दो आए, तो लिखिए: थ्री डैश टू।",
     "Here only two of the three trucks of sand came. Line three, two came: type 3-2."),
    ("engineer", "e10", "कमी की ख़बर उसी पल अब्बास जी और चड्ढा साहब, दोनों के पास पहुँचती है। और स्टॉक में वही चढ़ता है, "
     "जो सच में पहुँचा।",
     "The shortage reaches Abbas and Mr Chadda at that very moment. And stock gets only what really arrived."),
    ("engineer", "e11", "बटन दबाना भूल गए, तो दो दिन बाद पर्चेज़ डेस्क एक बार याद दिलाता है।",
     "Forget to tap, and two days later the Purchase Desk reminds you once."),
    ("engineer", "e12", "चाहें तो पर्चेज़ डेस्क को सीधे भी लिख सकते हैं। सामान इस्तेमाल हो, तो लिखिए: यूज़्ड टेन बैग "
     "सीमेंट। और स्टॉक लिखिए, तो साइट का पूरा स्टॉक आ जाता है।",
     "You can also write to the Purchase Desk directly. When material is used, type \"used 10 bag cement\". Type "
     "\"stock\" and the site's stock comes back."),
    ("engineer", "e13", "तो साइट इंजीनियर के लिए दो बातें। ज़रूरत ग्रुप में, साइट के नाम के साथ। और सामान आए, तो बटन "
     "दबाइए।",
     "So, two things for site engineers. Requirements go in the group, with the site's name. And when material "
     "arrives, tap the button."),

    # ---------------------------------------------------------------- Abbas
    ("abbas", "a1", "अब्बास जी, आपका काम तीन हिस्सों में है। ग्रुप की ज़रूरतें पर्चेज़ डेस्क तक पहुँचाना, स्लिप बनाना, "
     "और सामान भेजना।",
     "Abbas, your work has three parts: getting the group's requirements to the Purchase Desk, making the slip, and "
     "sending the material."),
    ("abbas", "a2", "दिन में एक या दो बार ग्रुप खोलिए। ज़रूरत वाले एक मैसेज को दबाकर रखिए, फिर बाक़ी नए मैसेज पर टैप "
     "करके उन्हें भी चुन लीजिए। लिखा हुआ, फ़ोटो, वॉइस नोट, सब एक साथ चलता है।",
     "Once or twice a day, open the group. Press and hold one requirement post, then tap the other new posts to "
     "select them too. Text, photos and voice notes can all go together."),
    ("abbas", "a3", "अब फ़ॉरवर्ड का बटन दबाइए, पर्चेज़ डेस्क चुनिए, और भेज दीजिए।",
     "Now tap Forward, pick Purchase Desk, and send."),
    ("abbas", "a4", "पर्चेज़ डेस्क हर मैसेज पढ़ता है, वॉइस नोट सुनता है, फ़ोटो में लिखी लिस्ट भी पढ़ता है, और सब कुछ "
     "साइट के हिसाब से लिखकर, आपको एक ही समरी भेजता है।",
     "The Purchase Desk reads every message, listens to the voice notes, reads the list in the photo, sorts "
     "everything by site, and sends you one summary."),
    ("abbas", "a5", "ओके सर जैसे मैसेज, जिनमें कोई सामान नहीं है, अपने आप छूट जाते हैं।",
     "Messages with no materials, like \"ok sir\", are skipped by themselves."),
    ("abbas", "a6", "जिस मैसेज में साइट का नाम नहीं था, उसके लिए तीन बटन आते हैं। सही साइट पर टैप कीजिए।",
     "For a message that didn't name a site, three buttons come. Tap the right site."),
    ("abbas", "a7", "कोई मात्रा ग़लत दर्ज हुई, तो लिखिए एन टू सिक्सटी बैग। और कोई चीज़ हटानी हो, तो लिखिए रिमूव एन टू।",
     "If a quantity was logged wrong, type \"N2 60 bag\". To take an item off, type \"remove N2\"."),
    ("abbas", "a8", "अब स्लिप। लिस्ट लिखिए। सारी खुली ज़रूरतें साइट के हिसाब से आ जाती हैं, साथ में एक पीडीएफ़, जिसे "
     "लेकर आप मार्केट जा सकते हैं।",
     "Now the slip. Type \"list\". Every open requirement comes back by site, with a PDF to take to the market."),
    ("abbas", "a9", "मार्केट से रेट लेकर, वैसे ही लिखिए जैसे अभी लिखते हैं: आइटम का नंबर, दुकान का नाम, और रेट। एक लाइन "
     "में एक दुकान और एक रेट।",
     "With the market's rates, write it the way you do now: the item's number, the shop's name and the rate. One "
     "shop and one rate per line."),
    ("abbas", "a10", "पर्चेज़ डेस्क स्लिप बना देता है, और हर लाइन को पिछली ख़रीद से मिलाकर देखता है।",
     "The Purchase Desk builds the slip and checks every line against past purchases."),
    ("abbas", "a11", "देखिए। सीमेंट का रेट पिछली बार से छह परसेंट ज़्यादा है। निकोबार के लिए चालीस बैग सीमेंट बारह तारीख़ "
     "को ही ख़रीदा गया था। और सागर हार्डवेयर नया वेंडर है।",
     "Look: cement is six percent above last time. Forty bags of cement were bought for Nicobar just on the "
     "twelfth. And Sagar Hardware is a new vendor."),
    ("abbas", "a12", "ये चेतावनियाँ चड्ढा साहब को भी दिखेंगी। सब ठीक हो, तो सेंड फ़ॉर अप्रूवल दबाइए।",
     "Mr Chadda sees these warnings too. If all is in order, tap Send for approval."),
    ("abbas", "a13", "चड्ढा साहब कुछ पूछें, तो सवाल यहाँ आता है। उसी मैसेज को दाईं ओर स्वाइप कीजिए, और जवाब लिखिए। "
     "जवाब सीधे उनके पास जाता है।",
     "If Mr Chadda asks something, the question comes here. Swipe that message to the right and type your answer. "
     "It goes straight to him."),
    ("abbas", "a14", "मंज़ूरी मिलते ही, पूरी या कुछ लाइनों की, साइन की हुई स्लिप आपके पास आती है। यहाँ लाइन पाँच मंज़ूर "
     "नहीं हुई, यानी वह नहीं ख़रीदनी।",
     "Once he approves, all or part, the signed slip comes to you. Here line five wasn't approved, so it must not "
     "be bought."),
    ("abbas", "a15", "नियम एक ही है: सिर्फ़ वही ख़रीदिए जो साइन की हुई स्लिप पर है, और उसी दुकान से।",
     "One rule: buy only what is on the signed slip, from the shop it names."),
    ("abbas", "a16", "सामान भेजने के बाद ग्रुप में वैसे ही पोस्ट कीजिए जैसे अभी करते हैं: लिस्ट की फ़ोटो, और साथ में कि "
     "किस बस या जहाज़ से गया। फिर वह पोस्ट भी पर्चेज़ डेस्क को फ़ॉरवर्ड कर दीजिए।",
     "After sending, post in the group as you do now: a photo of the list, and which bus or ship it went on. Then "
     "forward that post to the Purchase Desk too."),
    ("abbas", "a17", "पर्चेज़ डेस्क सामान को अप्रूव्ड स्लिप से मिलाता है, और साइट से पूछता है कि सब पहुँचा या नहीं।",
     "The Purchase Desk matches the items to the approved slip, and asks the site whether everything arrived."),
    ("abbas", "a18", "ग्रुप में पोस्ट नहीं किया, तो सीधे भी लिख सकते हैं: डिस्पैच, स्लिप का नंबर, साइट, और जहाज़ का नाम।",
     "If you didn't post in the group, you can also type it directly: dispatch, the slip number, the site and the "
     "ship's name."),
    ("abbas", "a19", "और कुछ भी बाक़ी हो, तो हर सुबह आठ बजे आपको आज की लिस्ट मिलती है: किस साइट का क्या बाक़ी है, और "
     "क्या अप्रूव होकर भी अभी तक भेजा नहीं गया।",
     "And whenever anything is open, every morning at eight you get today's list: what each site is still waiting "
     "for, and what is approved but not yet sent."),
    ("abbas", "a20", "तो अब्बास जी के लिए तीन बातें। ग्रुप से फ़ॉरवर्ड। लाइन लिखकर स्लिप। और भेजने वाली पोस्ट भी "
     "फ़ॉरवर्ड।",
     "So, three things for Abbas. Forward from the group. Write lines to make the slip. And forward the dispatch "
     "post too."),

    # ---------------------------------------------------------------- Mr Chadda
    ("md", "m1", "चड्ढा साहब, हर पर्चेज़ स्लिप अब पर्चेज़ डेस्क की चैट में आपके पास आएगी। पहले पीडीएफ़, फिर पूरी लिस्ट, "
     "और नीचे तीन बटन।",
     "Mr Chadda, every purchase slip now comes to you in the Purchase Desk chat: first the PDF, then the full list, "
     "and three buttons below."),
    ("md", "m2", "हर लाइन में साइट, सामान, मात्रा, रेट और दुकान है। जिस लाइन पर यह पीला निशान है, उसे ध्यान से देखिए।",
     "Every line has the site, item, quantity, rate and shop. Look carefully at any line with this yellow sign."),
    ("md", "m3", "निशान बताता है कि रेट पिछली बार से पाँच परसेंट से ज़्यादा है, या दुकान नई है, या साइट ने जितना माँगा "
     "उससे ज़्यादा ख़रीदा जा रहा है, या यही सामान उसी साइट के लिए दस दिन के अंदर ख़रीदा जा चुका है, या किसी साइट ने "
     "उसे माँगा ही नहीं।",
     "The sign means the rate is more than five percent above last time, or the shop is new, or more is being bought "
     "than the site asked for, or the same thing was bought for that site in the last ten days, or no site asked "
     "for it."),
    ("md", "m4", "कुछ पूछना हो, तो बस लिख दीजिए। जैसे: सीमेंट चार सौ बीस क्यों, पिछली बार तीन सौ पचानवे था।",
     "To ask something, just type it. Like: why is cement 420, last time it was 395?"),
    ("md", "m5", "सवाल अब्बास जी के पास चला जाता है, और स्लिप आपके फ़ैसले का इंतज़ार करती है। उनका जवाब इसी चैट में आता "
     "है।",
     "The question goes to Abbas, and the slip waits for your decision. His answer comes into this same chat."),
    ("md", "m6", "फ़ैसला वैसे ही लिखिए, जैसे ग्रुप में लिखते हैं। हाँ, ओके, या अब्बास डू इट, तो पूरी स्लिप मंज़ूर। नहीं, "
     "तो पूरी स्लिप नामंज़ूर।",
     "Write your decision the way you write in the group. \"Haan\", \"ok\" or \"Abbas do it\" approves the whole "
     "slip. \"Nahi\" rejects the whole slip."),
    ("md", "m7", "किसी एक लाइन को रोकना हो, तो उसका नंबर और नहीं लिखिए। जैसे फ़ाइव नहीं, यानी लाइन पाँच छोड़कर बाक़ी सब "
     "मंज़ूर। और कुछ ही लाइनें मंज़ूर करनी हों, तो ओनली वन टू।",
     "To stop one line, type its number and \"nahi\". \"5 nahi\" approves everything except line five. To approve "
     "only some lines: \"only 1 2\"."),
    ("md", "m8", "यहाँ सागर हार्डवेयर नया है, इसलिए लिखते हैं: फ़ाइव नहीं। पर्चेज़ डेस्क एक बार दिखाता है कि क्या मंज़ूर "
     "होगा और क्या नहीं। ठीक है, तो कन्फ़र्म दबाइए।",
     "Here Sagar Hardware is new, so we type \"5 nahi\". The Purchase Desk shows once what will be approved and what "
     "won't. If it's right, tap Confirm."),
    ("md", "m9", "अब साइन की हुई स्लिप जारी होती है: आपके नाम, आपके इनिशियल की मुहर, तारीख़, समय, और एक वेरिफ़िकेशन "
     "कोड के साथ।",
     "Now the signed slip is issued: with your name, your initials stamp, the date and time, and a verification "
     "code."),
    ("md", "m10", "इस क्यूआर कोड को स्कैन करके कोई भी देख सकता है कि स्लिप असल में कैसी मंज़ूर हुई थी। काग़ज़ पर कुछ भी "
     "अलग हो, तो समझिए स्लिप बदली गई है।",
     "Anyone can scan this QR code to see the slip exactly as it was approved. If the paper differs from that in "
     "anything, the slip has been changed."),
    ("md", "m11", "सबसे ज़रूरी बात: अप्रूवल सिर्फ़ आपके नंबर से होता है। आपकी हाँ के बिना किसी स्लिप पर आपका नाम नहीं "
     "आता।",
     "Most important: approval comes only from your number. Without your yes, no slip carries your name."),
    ("md", "m12", "बटन भी काम करते हैं: अप्रूव ऑल, रिजेक्ट, और आस्क लॉजिस्टिक्स। वॉइस नोट से जवाब दें, तो पर्चेज़ डेस्क "
     "दिखाता है कि उसने क्या सुना, और आपसे कन्फ़र्म करवाता है।",
     "The buttons work too: Approve all, Reject and Ask logistics. If you reply by voice note, the Purchase Desk "
     "shows what it heard and asks you to confirm."),
    ("md", "m13", "साइट पर कुछ कम पहुँचे, तो उसकी ख़बर आपको उसी समय मिलती है।",
     "If something reaches a site short, you hear about it at once."),
    ("md", "m14", "और हर शाम आठ बजे एक समरी: किस साइट का क्या बाक़ी है, और इस महीने कितना ख़र्च हुआ। कभी भी रिपोर्ट "
     "लिखकर इस महीने का ख़र्च देख सकते हैं, और पेंडिंग लिखकर वो स्लिप, जो आपका इंतज़ार कर रही हैं।",
     "And every evening at eight, a summary: what each site is waiting for, and what was spent this month. Type "
     "\"report\" any time for this month's spending, and \"pending\" for the slips waiting for you."),
    ("md", "m15", "ग्रुप में अब हर चीज़ पर अब्बास डू इट लिखने की ज़रूरत नहीं। स्लिप पर हाँ कीजिए, क्योंकि रेट वहीं "
     "दिखता है।",
     "In the group you no longer need to write \"Abbas do it\" on every item. Say yes on the slip, because that's "
     "where you see the rate."),

    # ---------------------------------------------------------------- the whole journey
    ("journey", "j1", "अब पूरा सफ़र एक साथ देखते हैं।", "Now the whole journey, together."),
    ("journey", "j2", "साइट ग्रुप में ज़रूरत डालती है। अब्बास जी उसे पर्चेज़ डेस्क को फ़ॉरवर्ड करते हैं, और रेट लगाकर "
     "स्लिप भेजते हैं।",
     "The site posts its requirement in the group. Abbas forwards it to the Purchase Desk, prices it and sends the "
     "slip."),
    ("journey", "j3", "चड्ढा साहब स्लिप पर हाँ करते हैं। साइन की हुई स्लिप अब्बास जी के पास आती है, और साइट को पता चलता "
     "है कि क्या ख़रीदा जाएगा।",
     "Mr Chadda says yes on the slip. The signed slip reaches Abbas, and the site learns what will be bought."),
    ("journey", "j4", "सामान जाता है, साइट बटन दबाकर बताती है कि क्या पहुँचा, और स्टॉक अपडेट होता है। गूगल जुड़ने के "
     "बाद, हर फ़ैसले वाली स्लिप गूगल ड्राइव में, और हर लाइन गूगल शीट में दर्ज होती है।",
     "The material goes, the site taps to say what arrived, and stock updates. Once Google is connected, every "
     "decided slip is filed in Google Drive and every line in a Google Sheet."),
    ("journey", "j5", "कोई दिक़्क़त हो, तो पर्चेज़ डेस्क को हाय भेजिए, या शिवांक को बताइए। धन्यवाद।",
     "Any trouble, send \"hi\" to the Purchase Desk, or tell Shivank. Thank you."),
]

LINE = {lid: dict(chapter=ch, id=lid, hi=hi, en=en) for ch, lid, hi, en in LINES}
