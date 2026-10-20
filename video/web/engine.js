// The tutorial's renderer: builds WhatsApp phones and overlays from build/film.json and sets every value from the
// time t alone (window.__seek(t)). No timers, no CSS transitions: the same t always gives the same frame.
import { spring, springs, settleTime, PRESETS } from "./motion.mjs";

const SW = 393, SH = 852;                 // phone screen, CSS px
const PW = 415, PH = 874;                 // phone with bezel
const BODY_TOP = 100;
const [SNAP_F, SNAP_Z] = PRESETS.snappy;
const [DEF_F, DEF_Z] = PRESETS.default;
const [HEAVY_F, HEAVY_Z] = PRESETS.heavy;

const ICON = {
  back: '<svg viewBox="0 0 24 24"><path d="M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20z"/></svg>',
  video: '<svg viewBox="0 0 24 24"><path d="M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11z"/></svg>',
  call: '<svg viewBox="0 0 24 24"><path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>',
  reply: '<svg viewBox="0 0 24 24"><path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="M12 17.3l6.2 3.7-1.6-7 5.4-4.7-7.2-.6L12 2 9.2 8.7 2 9.3l5.4 4.7-1.6 7z"/></svg>',
  del: '<svg viewBox="0 0 24 24"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z"/></svg>',
  fwd: '<svg viewBox="0 0 24 24"><path d="M14 9V5l7 7-7 7v-4.1c-5 0-8.5 1.6-11 5.1 1-5 4-10 11-11z"/></svg>',
  search: '<svg viewBox="0 0 24 24"><path d="M15.5 14h-.8l-.3-.3A6.5 6.5 0 1 0 14 15.5l.3.3v.8l5 5 1.5-1.5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>',
  ticks: '<svg viewBox="0 0 18 12"><path d="M17.4 1.1 16.3 0 8.2 8.1 7.6 7.5 6.5 8.6 8.2 10.3zM12.4 1.1 11.3 0 3.2 8.1 1.1 6 0 7.1l3.2 3.2z"/></svg>',
  mic: '<svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v7a3 3 0 0 0 3 3zm5.3-3a5.3 5.3 0 0 1-10.6 0H5a7 7 0 0 0 6 6.9V22h2v-3.1a7 7 0 0 0 6-6.9z"/></svg>',
  send: '<svg viewBox="0 0 24 24"><path d="M2 21l21-9L2 3v7l15 2-15 2z"/></svg>',
  emoji: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16zm-3.5-9A1.5 1.5 0 1 0 8.5 8a1.5 1.5 0 0 0 0 3zm7 0A1.5 1.5 0 1 0 15.5 8a1.5 1.5 0 0 0 0 3zM12 17.5c2.3 0 4.3-1.5 5-3.5H7c.7 2 2.7 3.5 5 3.5z"/></svg>',
  clip: '<svg viewBox="0 0 24 24"><path d="M16.5 6v11.5a4 4 0 0 1-8 0V5a2.5 2.5 0 0 1 5 0v10.5a1 1 0 0 1-2 0V6H10v9.5a2.5 2.5 0 0 0 5 0V5a4 4 0 0 0-8 0v12.5a5.5 5.5 0 0 0 11 0V6z"/></svg>',
  cam: '<svg viewBox="0 0 24 24"><path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM9 2 7.2 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3.2L15 2z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
  person: '<svg viewBox="0 0 24 24"><path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zm0 2.2c-3 0-9 1.5-9 4.5V21h18v-2.3c0-3-6-4.5-9-4.5z"/></svg>',
  group: '<svg viewBox="0 0 24 24"><path d="M16 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm-8 0a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13zm8 0c-.3 0-.6 0-1 .1 1.2.8 2 2 2 3.4V19h6v-2.5c0-2.3-4.7-3.5-7-3.5z"/></svg>',
  desk: '<svg viewBox="0 0 24 24"><path d="M19 3h-4.2A3 3 0 0 0 12 1a3 3 0 0 0-2.8 2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm-7 0a1 1 0 1 1 0 2 1 1 0 0 1 0-2zm-2 14-4-4 1.4-1.4 2.6 2.6 6.6-6.6L18 9z"/></svg>',
  chat: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 0 0-8.6 15l-1.4 5 5.2-1.4A10 10 0 1 0 12 2z"/></svg>',
  signal: '<svg viewBox="0 0 24 24"><path d="M2 22h20V2z"/></svg>',
  wifi: '<svg viewBox="0 0 24 24"><path d="M12 21 23.6 6.5A18.7 18.7 0 0 0 .4 6.5z"/></svg>',
  battery: '<svg viewBox="0 0 24 24"><path d="M16 4h-2V2h-4v2H8a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1z"/></svg>',
};

const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, u) => a + (b - a) * u;
const smooth = (u) => { u = clamp(u); return u * u * (3 - 2 * u); };
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const h = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
// opacity of something shown on [t0, t1): a quick fade at each end
const window01 = (t, t0, t1, fin = 0.25, fout = 0.25) => (t < t0 || t >= t1) ? 0 : Math.min(smooth((t - t0) / fin), smooth((t1 - t) / fout));
const bump = (t, t0, up, down) => t < t0 ? 0 : t < t0 + up ? smooth((t - t0) / up) : smooth(1 - (t - t0 - up) / down);

// WhatsApp's markup: *bold*, _italic_, ~strike~
function wamark(line) {
  let s = esc(line);
  s = s.replace(/\*([^*\n]+?)\*/g, "<b>$1</b>");
  s = s.replace(/(^|[\s(“"])_([^_\n]+?)_(?=$|[\s).,:;!?”"])/g, "$1<i>$2</i>");
  s = s.replace(/~([^~\n]+?)~/g, "<s>$1</s>");
  return s;
}

function avatar(spec, size) {
  const a = h("div", "av");
  a.style.width = a.style.height = size + "px";
  a.style.background = spec.color || "#9aa5ab";
  if (spec.icon) a.innerHTML = ICON[spec.icon];
  else a.textContent = spec.initials || "";
  if (!spec.icon) a.style.fontSize = Math.round(size * 0.4) + "px";
  return a;
}

let FILM = null;
const PH_ = {};        // phones by id
const OV = {};         // overlays

// ------------------------------------------------------------------------------------------------ phones
function buildPhone(id, spec) {
  const el = h("div", "phone");
  el.innerHTML = `<div class="bezel"></div><div class="screen"></div><div class="punch"></div>`;
  const tag = h("div", "tag", `${esc(spec.tag_hi || "")}<small>${esc(spec.tag_en || "")}</small>`);
  el.appendChild(tag);
  document.getElementById("world").appendChild(el);
  const screen = el.querySelector(".screen");
  const P = { id, spec, el, screen, tag, screens: {}, chats: {}, touches: [] };
  for (const [cid, chat] of Object.entries(spec.chats)) buildChat(P, cid, chat);
  if (spec.forward) buildForward(P, spec.forward);
  for (const [k, pdf] of Object.entries(spec.pdfs || {})) buildPdf(P, k, pdf);
  P.notif = h("div", "notif", `<div class="ap">${ICON.chat}</div><div><div class="nt"></div><div class="nb"></div></div>`);
  P.notif.style.opacity = 0;
  screen.appendChild(P.notif);
  P.focusEl = h("div", "focus");
  screen.appendChild(P.focusEl);
  for (let i = 0; i < 3; i++) {
    const t = h("div", "touch"), r = h("div", "ring");
    screen.appendChild(r); screen.appendChild(t);
    P.touches.push({ t, r });
  }
  PH_[id] = P;
}

function statusBar(dark) {
  const s = h("div", "status", `<span class="clock">10:00</span><span class="icons">${ICON.signal}${ICON.wifi}${ICON.battery}</span>`);
  if (dark) s.style.background = "#1f2224";
  return s;
}

function buildChat(P, cid, chat) {
  const scr = h("div", "scr");
  const status = statusBar();
  const head = h("div", "head", `<div class="back">${ICON.back}</div>`);
  head.appendChild(avatar(chat.avatar, 38));
  head.appendChild(h("div", "who", `<div class="name">${esc(chat.title)}</div><div class="sub">${esc(chat.sub || "")}</div>`));
  head.insertAdjacentHTML("beforeend", chat.kind === "group" ? `<div class="ic">${ICON.video}</div><div class="ic">${ICON.call}</div><div class="ic">${ICON.more}</div>`
    : `<div class="ic">${ICON.call}</div><div class="ic">${ICON.more}</div>`);
  const shead = h("div", "head sel", `<div class="back">${ICON.back}</div><div class="count">1</div><div class="ic">${ICON.reply}</div><div class="ic">${ICON.star}</div><div class="ic">${ICON.del}</div><div class="ic fwdic">${ICON.fwd}</div><div class="ic">${ICON.more}</div>`);
  shead.style.opacity = 0;
  const body = h("div", "body");
  const col = h("div", "col");
  body.appendChild(col);
  const inbar = h("div", "inbar", `<div class="field"><div class="em">${ICON.emoji}</div><div class="txt"><span class="ph">Message</span></div><div class="at">${ICON.clip}</div><div class="cam">${ICON.cam}</div></div><div class="go"><span class="m">${ICON.mic}</span><span class="s">${ICON.send}</span></div>`);
  const qprev = h("div", "qprev", `<div class="q"><div class="qn"></div><div class="qt"></div></div>`);
  qprev.style.opacity = 0;
  inbar.appendChild(qprev);
  scr.append(body, inbar, status, head, shead);
  P.screen.appendChild(scr);
  const C = { id: cid, spec: chat, scr, status, head, shead, body, col, inbar, qprev, rows: [], byId: {} };
  let prev = null;
  for (const m of chat.msgs) {
    const r = buildRow(m, prev);
    col.appendChild(r.row);
    C.rows.push(r);
    C.byId[m.id] = r;
    prev = m;
  }
  P.chats[cid] = C;
  P.screens["chat:" + cid] = { el: scr, kind: "chat", chat: C };
}

function buildRow(m, prev) {
  if (m.type === "date" || m.type === "sys") {
    const row = h("div", "row");
    row.style.justifyContent = "center";
    row.appendChild(h("div", "chip" + (m.type === "sys" ? " sys" : ""), esc(m.text)));
    return { m, row, lines: [], btns: [] };
  }
  const first = !prev || prev.type === "date" || prev.type === "sys" || prev.dir !== m.dir || (prev.sender || "") !== (m.sender || "");
  const row = h("div", `row ${m.dir}${first ? " first" : ""}`);
  row.insertAdjacentHTML("afterbegin", `<div class="selbg"></div><div class="selck">${ICON.check}</div><div class="swipe">${ICON.reply}</div>`);
  const wrap = h("div", "wrapb");
  const bub = h("div", "bub" + (m.type !== "text" ? " " + m.type : ""));
  let html = "";
  if (m.sender && first) html += `<span class="sender" style="color:${m.senderColor || "#1f7aec"}">${esc(m.sender)}</span>`;
  if (m.fwd) html += `<span class="fwd">${ICON.fwd}Forwarded</span>`;
  if (m.quote) html += `<span class="quote"><span class="qn">${esc(m.quote.who)}</span><span class="qt">${wamark(m.quote.text)}</span></span>`;
  if (m.type === "doc") {
    html += `<span class="pv" style="background-image:url('${m.doc.thumb}')"></span>` +
      `<span class="file"><span class="pdf">PDF</span><span><span class="fn">${esc(m.doc.name)}</span><span class="fm" style="display:block">${esc(m.doc.meta)}</span></span></span>`;
  } else if (m.type === "image") {
    html += `<span class="ph" style="display:block">${m.image.html}</span>`;
  } else if (m.type === "voice") {
    const bars = (m.voice.bars || []).map((v) => `<i style="height:${Math.round(4 + v * 20)}px"></i>`).join("");
    html += `<span class="vrow"><span class="vav"></span><span class="play">${ICON.play}</span><span class="wave">${bars}</span></span><span class="vd">${esc(m.voice.dur)}</span>`;
  }
  bub.innerHTML = html;
  if (m.type === "voice") {
    const vav = bub.querySelector(".vav");
    const a = avatar(m.voice.avatar, 42);
    vav.appendChild(a);
    vav.insertAdjacentHTML("beforeend", `<span class="mic">${ICON.mic}</span>`);
  }
  const lines = [];
  const textBlock = m.type === "doc" ? h("span", "cap") : m.type === "text" ? bub : h("span", "cap");
  if (m.type !== "text" && m.text) { textBlock.style.display = "block"; bub.appendChild(textBlock); }
  if (m.text) {
    for (const ln of m.text.split("\n")) {
      const l = h("span", "ln" + (ln.trim() ? "" : " gap"));
      l.innerHTML = `<span class="mark"></span><span class="tx">${wamark(ln)}</span>`;
      textBlock.appendChild(l);
      lines.push(l);
    }
  }
  const meta = h("span", "meta", `${esc(m.time || "")}${m.dir === "out" ? ICON.ticks : ""}`);
  (lines.length ? lines[lines.length - 1].querySelector(".tx") : bub).appendChild(meta);
  wrap.appendChild(bub);
  const btns = [];
  if (m.buttons && m.buttons.length) {
    const bw = h("div", "btns");
    for (const b of m.buttons) {
      const e = h("div", "btn", `<span class="press"></span><span>${esc(b)}</span>`);
      bw.appendChild(e);
      btns.push(e);
    }
    wrap.appendChild(bw);
  }
  row.appendChild(wrap);
  return { m, row, wrap, bub, lines, btns, selbg: row.querySelector(".selbg"), selck: row.querySelector(".selck"), swipe: row.querySelector(".swipe") };
}

function buildForward(P, spec) {
  const scr = h("div", "scr");
  const status = statusBar();
  const head = h("div", "head", `<div class="back">${ICON.back}</div><div class="who" style="margin-left:14px"><div class="name">Forward to…</div><div class="sub">${esc(spec.sub || "")}</div></div><div class="ic">${ICON.search}</div>`);
  const list = h("div", "fwdlist");
  const items = {};
  for (const sec of spec.sections) {
    list.appendChild(h("div", "sec", esc(sec.title)));
    for (const it of sec.items) {
      const e = h("div", "item");
      e.appendChild(h("div", "hl"));
      e.appendChild(avatar(it.avatar, 46));
      e.appendChild(h("div", "", `<div class="nm">${esc(it.name)}</div><div class="st">${esc(it.status || "")}</div>`));
      e.appendChild(h("div", "ck", ICON.check));
      list.appendChild(e);
      items[it.name] = e;
    }
  }
  const bar = h("div", "fwdbar", `<span class="sn"></span><div class="gof">${ICON.send}</div>`);
  scr.append(list, bar, status, head);
  P.screen.appendChild(scr);
  P.screens["fwd"] = { el: scr, kind: "fwd", items, bar, status };
}

function buildPdf(P, key, spec) {
  const scr = h("div", "scr pdfv");
  const status = statusBar(true);
  const head = h("div", "ph2", `${ICON.back}<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(spec.name)}</span>${ICON.more}`);
  const pages = h("div", "pages");
  const col = h("div", "pgcol");
  for (const src of spec.pages) { const im = h("img", "pg"); im.src = src; col.appendChild(im); }
  pages.appendChild(col);
  const pgn = h("div", "pgn", `1 / ${spec.pages.length}`);
  scr.append(pages, status, head, pgn);
  P.screen.appendChild(scr);
  P.screens["pdf:" + key] = { el: scr, kind: "pdf", col, pgn, spec, status };
}

// ------------------------------------------------------------------------------------------------ measuring
function measure() {
  for (const P of Object.values(PH_)) {
    for (const C of Object.values(P.chats)) {
      const viewH = SH - BODY_TOP - C.inbar.offsetHeight;
      C.viewH = viewH;
      C.baseInbar = C.inbar.offsetHeight;
      for (const r of C.rows) { r.top = r.row.offsetTop; r.h = r.row.offsetHeight; }
      const bottom = (r) => r.top + r.h + 12;
      const hist = C.rows.filter((r) => r.m.at < 0);
      const base = hist.length ? Math.max(0, bottom(hist[hist.length - 1]) - viewH) : 0;
      // WhatsApp's rule: a new message scrolls the chat only while you are at the bottom; after scrolling up to read,
      // the chat stays put until you send something or scroll back down
      const ev = [];
      for (const r of C.rows) if (r.m.at >= 0 && r.m.type !== "date" && r.m.type !== "sys") ev.push({ t: r.m.at, k: r.m.dir === "out" ? 0 : 1, y: Math.max(0, bottom(r) - viewH) });
      for (const s of C.spec.scroll || []) {
        const r = C.byId[s.to];
        if (!r) throw new Error(`scroll to unknown message ${s.to}`);
        let y = s.align === "top" ? r.top - 8 : s.align === "center" ? r.top + r.h / 2 - viewH / 2 : bottom(r) - viewH;
        y += s.off || 0;
        ev.push({ t: s.t, k: 2, y: clamp(y, 0, Math.max(0, C.col.offsetHeight - viewH)), pin: s.align !== "bottom" });
      }
      ev.sort((a, b) => a.t - b.t || a.k - b.k);
      const ch = [];
      let pinned = false;
      for (const e of ev) {
        if (e.k === 1 && pinned) continue;
        if (e.k === 0) pinned = false;
        if (e.k === 2) pinned = e.pin;
        ch.push([e.t, e.y]);
      }
      C.scrollBase = base;
      C.scrollCh = ch;
    }
  }
}

// ------------------------------------------------------------------------------------------------ per-frame updates
function lastAt(track, t) {  // the last [time, value] entry at or before t
  let v = null;
  for (const e of track) { if (e[0] <= t) v = e; else break; }
  return v;
}

function updateChat(P, C, t) {
  const spec = C.spec;
  // input bar: typing, quote preview, send
  const typ = (spec.typing || []).find((x) => t >= x.t0 && t < x.send);
  const txt = C.inbar.querySelector(".txt");
  let shown = "";
  if (typ) {
    const n = Math.round(typ.text.length * clamp((t - typ.t0) / Math.max(0.01, typ.t1 - typ.t0)));
    shown = typ.text.slice(0, n);
  }
  const blink = typ && (t > typ.t1 ? Math.floor((t - typ.t1) * 2.2) % 2 === 0 : true);
  const key = shown + (blink ? "|" : "");
  if (C._txt !== key) {
    txt.innerHTML = shown ? `<span>${esc(shown)}${blink ? '<span class="caret"></span>' : ""}</span>` : `<span class="ph">Message</span>`;
    C._txt = key;
  }
  C.inbar.querySelector(".go .m").style.opacity = shown ? 0 : 1;
  C.inbar.querySelector(".go .s").style.opacity = shown ? 1 : 0;
  const q = (spec.typing || []).find((x) => x.quote && t >= x.qt && t < x.send + 0.05);
  if (q) {
    C.qprev.querySelector(".qn").textContent = q.quote.who;
    C.qprev.querySelector(".qt").innerHTML = wamark(q.quote.text);
  }
  C.qprev.style.opacity = q ? smooth((t - q.qt) / 0.2) : 0;
  const extra = C.inbar.offsetHeight - C.baseInbar + (q ? C.qprev.offsetHeight - 6 : 0);
  C.body.style.bottom = C.baseInbar + Math.max(0, extra) + "px";
  // scroll
  const sc = springs(t, C.scrollBase, C.scrollCh, DEF_F, DEF_Z) + Math.max(0, extra);
  C.col.style.transform = `translateY(${-sc}px)`;
  C.scrollNow = sc;
  // messages
  const sel = spec.select || [];
  let nsel = 0;
  for (const r of C.rows) {
    const a = r.m.at;
    if (t < a) { r.row.style.opacity = 0; continue; }
    const u = spring(t - a, SNAP_F, SNAP_Z);
    r.row.style.opacity = clamp(u * 1.6);
    r.row.style.transform = a >= 0 && t - a < 1 ? `translateY(${(1 - u) * 14}px) scale(${0.97 + 0.03 * u})` : "";
    if (!r.selbg) continue;
    const s = sel.find((x) => x.msg === r.m.id && t >= x.t - 0.2 && t < x.until + 0.2) || sel.find((x) => x.msg === r.m.id);
    const on = s && t >= s.t && t < s.until;
    if (on) nsel++;
    const so = s ? window01(t, s.t, s.until, 0.12, 0.12) : 0;
    r.selbg.style.opacity = so;
    r.selck.style.opacity = so;
    const sw = (spec.swipes || []).find((x) => x.msg === r.m.id);
    const sx = sw ? bump(t, sw.t, 0.25, 0.35) : 0;
    r.wrap.style.transform = sx ? `translateX(${sx * 72}px)` : "";
    r.swipe.style.opacity = sx;
    for (const mk of r.m.marks || []) {
      const v = t < mk.t0 ? 0 : t < mk.t1 ? spring(t - mk.t0, DEF_F, DEF_Z) : 1 - smooth((t - mk.t1) / 0.3);
      for (let k = mk.a; k <= mk.b; k++) if (r.lines[k]) r.lines[k].querySelector(".mark").style.transform = `scaleX(${clamp(v)})`;
    }
  }
  C.head.style.opacity = nsel ? 0 : 1;
  C.shead.style.opacity = nsel ? 1 : 0;
  C.shead.querySelector(".count").textContent = String(nsel);
  // status bar clock: the newest visible message's time
  const clk = chatClock(C, t);
  C.status.querySelector(".clock").textContent = clk;
  return clk;
}

function chatClock(C, t) {
  let clk = C.spec.clock || "10:00";
  for (const r of C.rows) if (r.m.at <= t && r.m.clock) clk = r.m.clock;
  return clk;
}

function screenAt(P, t) {
  const sc = P.spec.screens;
  let i = -1;
  for (let k = 0; k < sc.length; k++) if (sc[k][0] <= t) i = k;
  return i;
}

function updatePhone(P, t) {
  const sc = P.spec.screens;
  const i = screenAt(P, t);
  const cur = sc[Math.max(0, i)];
  const prev = i > 0 ? sc[i - 1] : null;
  const DUR = 0.34;
  const u = cur && i >= 0 && prev && cur[2] !== "cut" ? smooth((t - cur[0]) / DUR) : 1;
  for (const [k, S] of Object.entries(P.screens)) {
    const isCur = cur && k === cur[1];
    const isPrev = prev && u < 1 && k === prev[1];
    S.el.style.display = isCur || isPrev ? "block" : "none";
    if (!(isCur || isPrev)) continue;
    let x = 0, f = 0;
    if (cur[2] === "pop") { if (isPrev) x = SW * u; if (isCur) { x = -80 * (1 - u); f = 1 - u; } }
    else { if (isCur) x = SW * (1 - u); if (isPrev) { x = -80 * u; f = u; } }
    S.el.style.transform = x ? `translateX(${x}px)` : "";
    S.el.style.zIndex = isCur ? (cur[2] === "pop" ? 1 : 2) : (cur[2] === "pop" ? 2 : 1);
    S.el.style.filter = f ? `brightness(${1 - 0.25 * f})` : "";
  }
  // the clock on a screen that is not a chat: that of the chat shown before it
  let clk = "10:00";
  for (let k = Math.max(0, i); k >= 0; k--) if (sc[k] && sc[k][1].startsWith("chat:")) { clk = chatClock(P.chats[sc[k][1].slice(5)], t); break; }
  for (const C of Object.values(P.chats)) {
    const S = P.screens["chat:" + C.id];
    if (S.el.style.display !== "none") updateChat(P, C, t);
  }
  const F = P.screens.fwd;
  if (F && F.el.style.display !== "none") {
    const fs = P.spec.forward;
    const pk = (fs.picks || []).find((x) => t >= x.t && t < x.until);
    for (const [name, el] of Object.entries(F.items)) {
      const on = pk && name === pk.name;
      el.querySelector(".ck").style.opacity = on ? spring(t - pk.t, SNAP_F, SNAP_Z) : 0;
      el.querySelector(".hl").style.opacity = on ? 1 : 0;
    }
    F.bar.style.transform = `translateY(${pk ? (1 - spring(t - pk.t, SNAP_F, SNAP_Z)) * 90 : 90}px)`;
    F.bar.querySelector(".sn").textContent = pk ? pk.name : "";
    F.status.querySelector(".clock").textContent = clk;
  }
  for (const [k, S] of Object.entries(P.screens)) {
    if (S.kind !== "pdf" || S.el.style.display === "none") continue;
    const tr = S.spec.scroll || [];
    const y = springs(t, 0, tr, DEF_F, DEF_Z);
    S.col.style.transform = `translateY(${-y}px)`;
    const pageH = S.col.offsetHeight / S.spec.pages.length;
    S.pgn.textContent = `${Math.min(S.spec.pages.length, 1 + Math.floor((y + 200) / pageH))} / ${S.spec.pages.length}`;
    S.status.querySelector(".clock").textContent = S.spec.clock || clk;
  }
  // notification
  const n = (P.spec.notifs || []).find((x) => t >= x.t0 - 0.1 && t < x.t1 + 0.6);
  if (n) {
    P.notif.querySelector(".nt").innerHTML = `${esc(n.title)}<span>now</span>`;
    P.notif.querySelector(".nb").textContent = n.text;
    const v = t < x1(n) ? spring(t - n.t0, SNAP_F, SNAP_Z) : 1 - spring(t - n.t1, DEF_F, DEF_Z);
    P.notif.style.opacity = v > 0.001 ? 1 : 0;
    P.notif.style.transform = `translateY(${(1 - v) * -130}px)`;
  } else P.notif.style.opacity = 0;
}
const x1 = (n) => n.t1;

// where something is on the phone's screen (screen px), now
function locate(P, target) {
  const sr = P.screen.getBoundingClientRect();
  const k = sr.width / SW;
  let el = null;
  if (target.btn) el = P.chats[target.btn[0]].byId[target.btn[1]].btns[target.btn[2]];
  else if (target.msg) el = P.chats[target.msg[0]].byId[target.msg[1]].bub;
  else if (target.doc) el = P.chats[target.doc[0]].byId[target.doc[1]].bub.querySelector(".pv");
  else if (target.lines) {
    const r = P.chats[target.lines[0]].byId[target.lines[1]];
    const a = r.lines[target.lines[2]].getBoundingClientRect(), b = r.lines[target.lines[3]].getBoundingClientRect();
    const br = r.bub.getBoundingClientRect();
    return { x: (br.left - sr.left) / k, y: (a.top - sr.top) / k, w: br.width / k, h: (b.bottom - a.top) / k };
  } else if (target.el === "send") el = P.chats[target.chat].inbar.querySelector(".go");
  else if (target.el === "fwdicon") el = P.chats[target.chat].shead.querySelector(".fwdic");
  else if (target.el === "contact") el = P.screens.fwd.items[target.name];
  else if (target.el === "fwdsend") el = P.screens.fwd.bar.querySelector(".gof");
  else if (target.el === "input") el = P.chats[target.chat].inbar.querySelector(".field");
  else if (target.el === "pdfpage") {
    const S = P.screens["pdf:" + target.pdf];
    el = S.col.children[target.page];
  } else if (target.rect) return { x: target.rect[0], y: target.rect[1], w: target.rect[2], h: target.rect[3] };
  if (!el) throw new Error("cannot locate " + JSON.stringify(target));
  const r = el.getBoundingClientRect();
  return { x: (r.left - sr.left) / k, y: (r.top - sr.top) / k, w: r.width / k, h: r.height / k };
}

function updateTouches(P, t) {
  const taps = P.spec.taps || [];
  let used = 0;
  for (const tp of taps) {
    const t0 = tp.t - 0.3, t1 = tp.t + (tp.hold || 0) + 0.45;
    if (t < t0 || t > t1 || used >= P.touches.length) continue;
    const { t: dot, r: ring } = P.touches[used++];
    const b = locate(P, tp.target);
    const x = b.x + b.w * (tp.fx ?? 0.5), y = b.y + b.h * (tp.fy ?? 0.5);
    const come = smooth((t - t0) / 0.25), go = 1 - smooth((t - (tp.t + (tp.hold || 0) + 0.15)) / 0.3);
    dot.style.left = x + "px"; dot.style.top = y + "px";
    ring.style.left = x + "px"; ring.style.top = y + "px";
    const press = t >= tp.t ? (tp.hold ? 0.82 : 0.82 + 0.18 * smooth((t - tp.t - 0.12) / 0.2)) : 1.25 - 0.25 * come;
    dot.style.opacity = Math.min(come, go);
    dot.style.transform = `scale(${press})`;
    const rr = t >= tp.t + (tp.hold || 0) ? clamp((t - tp.t - (tp.hold || 0)) / 0.45) : 0;
    ring.style.opacity = rr > 0 ? (1 - rr) * 0.9 : 0;
    ring.style.transform = `scale(${1 + rr * 1.4})`;
    if (tp.target.btn) {
      const btn = P.chats[tp.target.btn[0]].byId[tp.target.btn[1]].btns[tp.target.btn[2]];
      btn.querySelector(".press").style.opacity = bump(t, tp.t - 0.05, 0.1, 0.4);
    }
  }
  for (let i = used; i < P.touches.length; i++) { P.touches[i].t.style.opacity = 0; P.touches[i].r.style.opacity = 0; }
  // the focus ring
  const f = (FILM.focus || []).find((x) => x.phone === P.id && t >= x.t0 - 0.05 && t < x.t1 + 0.3);
  if (f) {
    const b = locate(P, f.target);
    const pad = f.pad ?? 6;
    Object.assign(P.focusEl.style, { left: b.x - pad + "px", top: b.y - pad + "px", width: b.w + 2 * pad + "px", height: b.h + 2 * pad + "px" });
    P.focusEl.style.opacity = window01(t, f.t0, f.t1, 0.25, 0.3);
  } else P.focusEl.style.opacity = 0;
}

// ------------------------------------------------------------------------------------------------ layout + camera
function trackValue(t, track, id, key, dflt, f = DEF_F, z = DEF_Z) {
  const ch = [];
  let base = null;
  for (const [tt, lay] of track) {
    const v = lay[id] && lay[id][key];
    if (v === undefined) continue;
    if (base === null) { base = v; continue; }
    ch.push([tt, v]);
  }
  if (base === null) return dflt;
  return springs(t, base, ch, f, z);
}

function phoneLocalToWorld(P, x, y) {
  const s = P.ws;
  return [P.wx + (11 + x - PW / 2) * s, P.wy + (11 + y - PH / 2) * s];
}

function updateLayout(t) {
  const L = FILM.layout;
  for (const P of Object.values(PH_)) {
    const x = trackValue(t, L, P.id, "x", -2000, HEAVY_F, HEAVY_Z);
    const y = trackValue(t, L, P.id, "y", 540, HEAVY_F, HEAVY_Z);
    const s = trackValue(t, L, P.id, "s", 1, HEAVY_F, HEAVY_Z);
    const o = trackValue(t, L, P.id, "o", 0, DEF_F, DEF_Z);
    const tg = trackValue(t, L, P.id, "tag", 0, DEF_F, DEF_Z);
    P.wx = x; P.wy = y; P.ws = s;
    P.el.style.transform = `translate(${x - PW / 2}px, ${y - PH / 2}px) scale(${s})`;
    P.el.style.opacity = clamp(o);
    P.el.style.display = o < 0.002 ? "none" : "block";
    P.tag.style.opacity = clamp(tg);
    P.visible = o > 0.002;
  }
}

function camTarget(spec) {
  if (spec.phone) {
    const P = PH_[spec.phone];
    let cx = SW / 2, cy = SH / 2;
    if (spec.target) {
      const b = locate(P, spec.target);
      cx = b.x + b.w / 2; cy = b.y + b.h / 2;
      if (spec.anchor === "top") cy = b.y + (1080 / 2 - 60) / spec.z / P.ws;
    }
    cx += spec.dx || 0; cy += spec.dy || 0;
    const [wx, wy] = phoneLocalToWorld(P, cx, cy);
    return { x: wx, y: wy, z: spec.z };
  }
  return { x: spec.x ?? 960, y: spec.y ?? 540, z: spec.z ?? 1 };
}

function updateCamera(t) {
  // each change springs from the previous target; start from the last change that has fully settled, and evaluate
  // dynamic targets (an element on a phone) now
  const cams = FILM.cam;
  let j = 0;
  for (let k = 0; k < cams.length; k++) {
    const sp = cams[k][1];
    if (cams[k][0] + settleTime(sp.f || DEF_F, sp.zeta || DEF_Z) <= t) j = k; else if (cams[k][0] > t) break;
  }
  let prev = camTarget(cams[j][1]);
  let cx = prev.x, cy = prev.y, lz = Math.log(prev.z);
  for (let k = j + 1; k < cams.length; k++) {
    const [tt, spec] = cams[k];
    if (tt > t) break;
    const tg = camTarget(spec);
    const u = spring(t - tt, spec.f || DEF_F, spec.zeta || DEF_Z);
    cx += (tg.x - prev.x) * u; cy += (tg.y - prev.y) * u; lz += (Math.log(tg.z) - Math.log(prev.z)) * u;
    prev = tg;
  }
  const z = Math.exp(lz);
  const w = document.getElementById("world");
  w.style.transform = `translate(${960 - cx * z}px, ${540 - cy * z}px) scale(${z})`;
  return z;
}

// ------------------------------------------------------------------------------------------------ overlays
function buildOverlays() {
  const fr = document.getElementById("overlay");
  OV.panel = h("div", "panel");
  OV.persona = h("div", "persona");
  OV.step = h("div", "step");
  OV.flow = h("div", "flow");
  OV.panel.append(OV.persona, OV.step, OV.flow);
  fr.appendChild(OV.panel);
  const nodes = FILM.flowNodes || [];
  OV.flowNodes = nodes.map((n, i) => {
    if (i) OV.flow.appendChild(h("div", "ar"));
    const e = h("div", "nd", `<div class="ic">${n.icon}</div><div class="lb">${esc(n.hi)}<small>${esc(n.en)}</small></div>`);
    OV.flow.appendChild(e);
    return e;
  });
  OV.items = (FILM.items || []).map((it) => {
    let e;
    if (it.kind === "node") e = h("div", "node", `<div class="ic">${it.icon}</div><div class="lb">${esc(it.hi)}<small>${esc(it.en || "")}</small></div>`);
    else if (it.kind === "edge") e = h("div", "edge");
    else if (it.kind === "token") e = h("div", "token", esc(it.text));
    else if (it.kind === "badge") e = h("div", "badge", `${esc(it.hi)}${it.en ? `<small>${esc(it.en)}</small>` : ""}`);
    else if (it.kind === "html") e = h("div", it.cls || "", it.html);
    e.style.position = "absolute";
    if (it.w) e.style.width = it.w + "px";
    (it.layer === "world" ? document.getElementById("world") : fr).appendChild(e);
    return { it, e };
  });
  OV.card = h("div", "card");
  OV.card.style.opacity = 0;
  fr.appendChild(OV.card);
}

function updateOverlays(t, z) {
  // step panel
  const st = (FILM.panel || []).find((p) => t >= p.t0 - 0.05 && t < p.t1 + 0.05);
  if (st) {
    const key = st.t0 + "|" + st.h;
    if (OV._step !== key) {
      OV.step.innerHTML = `${st.k ? `<div class="k">${esc(st.k)}</div>` : ""}<div class="h">${esc(st.h)}</div>` +
        `${st.e ? `<div class="e">${esc(st.e)}</div>` : ""}${st.cmd ? `<div class="cmd" style="font-size:${Math.min(42, Math.floor(880 / (0.61 * Math.max(...st.cmd.split("\n").map((x) => x.length)))))}px">${st.lbl ? `<span class="lbl">${esc(st.lbl)}</span>` : ""}${esc(st.cmd)}</div>` : ""}`;
      OV._step = key;
    }
    const v = window01(t, st.t0, st.t1, 0.3, 0.22);
    OV.step.style.opacity = v;
    OV.step.style.transform = `translateY(${(1 - spring(t - st.t0, SNAP_F, SNAP_Z)) * 24}px)`;
  } else OV.step.style.opacity = 0;
  const pe = (FILM.persona || []).find((p) => t >= p.t0 && t < p.t1);
  if (pe) {
    const key = pe.name + pe.t0;
    if (OV._pe !== key) {
      OV.persona.innerHTML = "";
      OV.persona.appendChild(avatar(pe.avatar, 76));
      OV.persona.appendChild(h("div", "", `<div class="pn">${esc(pe.name)}</div><div class="pr">${esc(pe.role)}</div>`));
      OV._pe = key;
    }
    OV.persona.style.opacity = window01(t, pe.t0, pe.t1, 0.4, 0.4);
  } else OV.persona.style.opacity = 0;
  const fl = (FILM.flow || []).find((p) => t >= p.t0 && t < p.t1);
  OV.flow.style.opacity = fl ? window01(t, fl.t0, fl.t1, 0.4, 0.4) : 0;
  if (fl) OV.flowNodes.forEach((e, i) => {
    const on = fl.active.includes(i);
    e.style.opacity = on ? 1 : 0.38;
    e.querySelector(".ic").style.borderColor = on ? "#008069" : "#c9d8d2";
    e.querySelector(".ic").style.transform = on ? "scale(1.08)" : "";
  });
  // the panel sits beside the phone: it fades out whenever the camera moves in
  OV.panel.style.opacity = clamp((1.12 - z) / 0.1);
  // free items
  for (const { it, e } of OV.items) {
    let o = window01(t, it.t0, it.t1, it.fin ?? 0.35, it.fout ?? 0.3);
    if (o <= 0) { e.style.opacity = 0; e.style.display = "none"; continue; }
    e.style.display = "";
    let x = it.x, y = it.y;
    if (it.path) {           // [[t, x, y], ...] eased between points
      const p = it.path;
      if (t <= p[0][0]) { x = p[0][1]; y = p[0][2]; }
      else if (t >= p[p.length - 1][0]) { x = p[p.length - 1][1]; y = p[p.length - 1][2]; }
      else for (let i = 0; i < p.length - 1; i++) if (t >= p[i][0] && t < p[i + 1][0]) {
        const u = smooth((t - p[i][0]) / (p[i + 1][0] - p[i][0]));
        x = lerp(p[i][1], p[i + 1][1], u); y = lerp(p[i][2], p[i + 1][2], u);
      }
    }
    let sc = 1;
    if (it.pop) sc = 0.7 + 0.3 * spring(t - it.t0, ...PRESETS.playful);
    if (it.kind === "edge") {
      const len = Math.hypot(it.x2 - it.x, it.y2 - it.y), ang = Math.atan2(it.y2 - it.y, it.x2 - it.x);
      const grow = spring(t - it.t0, DEF_F, DEF_Z);
      e.style.width = len * grow + "px";
      e.style.left = it.x + "px"; e.style.top = it.y + "px";
      e.style.transform = `rotate(${ang}rad)`;
    } else {
      e.style.left = x + "px"; e.style.top = y + "px";
      e.style.transform = `${it.center ? "translate(-50%, -50%) " : ""}scale(${sc})`;
    }
    e.style.opacity = o;
  }
  // chapter cards (full frame): cut in, then slide up and away, opaque all the time (text never cross-fades)
  const c = (FILM.cards || []).find((p) => t >= p.t0 && t < p.t1 + 0.75);
  if (c) {
    const key = c.t0;
    if (OV._card !== key) {
      OV.card.innerHTML = `<div class="n">${esc(c.n)}</div><div class="t">${esc(c.t)}</div><div class="e">${esc(c.e)}</div>${c.w ? `<div class="w">${esc(c.w)}</div>` : ""}`;
      OV._card = key;
    }
    OV.card.style.opacity = 1;
    const out = t < c.t1 ? 0 : smooth((t - c.t1) / 0.7);
    const inner = 1 - spring(t - c.t0, HEAVY_F, HEAVY_Z);
    OV.card.style.transform = `translateY(${-1090 * out}px)`;
    for (const ch of OV.card.children) ch.style.transform = `translateY(${inner * 40}px)`;
  } else OV.card.style.opacity = 0;
}

// ------------------------------------------------------------------------------------------------ seek
function seek(t) {
  updateLayout(t);
  for (const P of Object.values(PH_)) if (P.visible) updatePhone(P, t);
  const z = updateCamera(t);
  for (const P of Object.values(PH_)) if (P.visible) updateTouches(P, t);
  updateOverlays(t, z);
}

async function main() {
  try {
    const url = new URLSearchParams(location.search).get("film") || "../build/film.json";
    FILM = await (await fetch(url)).json();
    for (const [id, spec] of Object.entries(FILM.phones)) buildPhone(id, spec);
    buildOverlays();
    await document.fonts.ready;
    await Promise.all([...document.images].map((im) => im.complete ? 0 : new Promise((r) => { im.onload = im.onerror = r; })));
    // background images used as previews
    const urls = new Set();
    document.querySelectorAll(".pv").forEach((e) => { const m = /url\("?'?([^"')]+)/.exec(e.style.backgroundImage); if (m) urls.add(m[1]); });
    await Promise.all([...urls].map((u) => new Promise((r) => { const im = new Image(); im.onload = im.onerror = r; im.src = u; })));
    measure();
    window.__seek = seek;
    window.__PH = PH_;
    window.__film = FILM;
    seek(0);
    window.__ready = true;
  } catch (e) {
    window.__error = String(e && e.stack || e);
    console.error(e);
  }
}
main();
