// Frame-exact renderer (after the youtube repo's web engine, film 07): Playwright drives Chromium, seeks the page to
// each frame's time, screenshots it and pipes the frames into ffmpeg. Run from anywhere:
//
//   node video/web/render.mjs --stills 12.5,30,61         # PNGs at film times -> video/build/stills/
//   node video/web/render.mjs --every 2 --from 0 --to 60  # a still every 2 s
//   node video/web/render.mjs --video --jobs 4            # the whole film -> video/build/picture.mp4
//   node video/web/render.mjs --video --from 120 --to 180 # a part -> video/build/picture_120-180.mp4
//   node video/web/render.mjs --textcheck [--step 0.2]    # no text overlaps other text on any frame (L10)
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { once } from "node:events";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(WEB, "..");           // video/
const BUILD = path.join(ROOT, "build");
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith("--")) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith("--") ? all[i + 1] : true]);
  return acc;
}, []));
const film = JSON.parse(fs.readFileSync(path.join(BUILD, "film.json"), "utf8"));
const FPS = film.fps;

const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".png": "image/png",
  ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff", ".json": "application/json", ".jpg": "image/jpeg" };
const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(new URL(req.url, "http://x").pathname));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": MIME[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const PORT = server.address().port;
const browser = await chromium.launch({ args: ["--font-render-hinting=none", "--force-color-profile=srgb", "--disable-lcd-text", "--hide-scrollbars"] });

async function open() {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on("console", (m) => { if (m.type() === "error") console.error(`[page] ${m.text()}`); });
  page.on("pageerror", (e) => console.error(`[page] ${e}`));
  await page.goto(`http://127.0.0.1:${PORT}/web/index.html`);
  await page.waitForFunction(() => window.__ready || window.__error, null, { timeout: 120000 });
  const err = await page.evaluate(() => window.__error);
  if (err) throw new Error(err);
  const cdp = await page.context().newCDPSession(page);
  const shot = async (t, format = "png") => {
    await page.evaluate((tt) => window.__seek(tt), t);
    const { data } = await cdp.send("Page.captureScreenshot", format === "png" ? { format: "png" } : { format: "jpeg", quality: 94 });
    return Buffer.from(data, "base64");
  };
  return { page, shot };
}

async function stills(times) {
  const { page, shot } = await open();
  const dir = path.join(BUILD, "stills");
  fs.mkdirSync(dir, { recursive: true });
  for (const t of times) fs.writeFileSync(path.join(dir, `t${t.toFixed(2).padStart(7, "0")}.png`), await shot(t));
  await page.close();
  console.log(`${times.length} stills -> ${dir}`);
}

async function renderRange(f0, f1, out) {
  const { page, shot } = await open();
  const tmp = out.replace(/\.mp4$/, ".part.mp4");
  const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-",
    "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-tune", "animation", "-pix_fmt", "yuv420p", "-r", String(FPS),
    "-g", String(FPS * 2), tmp], { stdio: ["pipe", "inherit", "inherit"] });
  const t0 = Date.now();
  for (let i = f0; i < f1; i++) {
    const buf = await shot(i / FPS, "jpeg");
    if (!ff.stdin.write(buf)) await once(ff.stdin, "drain");
    if ((i - f0) % 600 === 0) console.log(`  ${path.basename(out)} ${i - f0}/${f1 - f0}`);
  }
  ff.stdin.end();
  await once(ff, "close");
  fs.renameSync(tmp, out);
  await page.close();
  console.log(`  ${path.basename(out)}: ${f1 - f0} frames in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
}

async function video() {
  const from = Number(args.from || 0), to = Math.min(Number(args.to || film.duration), film.duration);
  const F0 = Math.round(from * FPS), F1 = Math.round(to * FPS);
  const jobs = Number(args.jobs || 4);
  const per = Math.ceil((F1 - F0) / jobs);
  const dir = path.join(BUILD, "chunks");
  fs.mkdirSync(dir, { recursive: true });
  const parts = [];
  for (let j = 0; j < jobs; j++) {
    const a = F0 + j * per, b = Math.min(F1, a + per);
    if (a < b) parts.push([a, b, path.join(dir, `c${String(j).padStart(2, "0")}_${a}_${b}.mp4`)]);
  }
  await Promise.all(parts.map(([a, b, o]) => renderRange(a, b, o)));
  const list = path.join(dir, "list.txt");
  fs.writeFileSync(list, parts.map((p) => `file '${p[2]}'`).join("\n"));
  const name = args.from || args.to ? `picture_${from}-${to}.mp4` : "picture.mp4";
  const out = path.join(BUILD, name);
  await once(spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", out + ".part.mp4"],
    { stdio: "inherit" }), "close");
  fs.renameSync(out + ".part.mp4", out);
  for (const p of parts) fs.unlinkSync(p[2]);
  console.log(`-> ${out} (${F1 - F0} frames)`);
}

// Text never overlaps other text: every visible text run's glyph boxes, from the frame's own layout.
async function textcheck() {
  const { page } = await open();
  const step = Number(args.step || 0.2);
  const from = Number(args.from || 0), to = Number(args.to || film.duration);
  const found = [];
  for (let t = from; t < to; t += step) {
    const hits = await page.evaluate((tt) => {
      window.__seek(tt);
      const vis = (el) => {
        for (let e = el; e && e !== document.body; e = e.parentElement) {
          const cs = getComputedStyle(e);
          if (cs.display === "none" || cs.visibility === "hidden" || Number(cs.opacity) < 0.05) return false;
        }
        return true;
      };
      const boxes = [];
      const walker = document.createTreeWalker(document.getElementById("frame"), NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.textContent.trim()) continue;
        const el = n.parentElement;
        if (!vis(el)) continue;
        const r = document.createRange();
        r.selectNodeContents(n);
        for (const b of r.getClientRects()) {
          if (b.width < 2 || b.height < 2) continue;
          if (b.right < 0 || b.bottom < 0 || b.left > 1920 || b.top > 1080) continue;
          // the clip of the phone screen / chat body
          let clip = null;
          for (let e = el; e; e = e.parentElement) if (e.classList && (e.classList.contains("body") || e.classList.contains("screen") || e.classList.contains("pages"))) { clip = e.getBoundingClientRect(); break; }
          if (clip && (b.bottom <= clip.top + 1 || b.top >= clip.bottom - 1)) continue;
          const shrink = b.height * 0.18;
          boxes.push({ el, l: b.left + 1, r: b.right - 1, t: b.top + shrink, b: b.bottom - shrink, s: n.textContent.trim().slice(0, 30) });
        }
      }
      const out = [];
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
        const A = boxes[i], B = boxes[j];
        if (A.el === B.el || A.el.contains(B.el) || B.el.contains(A.el)) continue;
        if (A.l < B.r && B.l < A.r && A.t < B.b && B.t < A.b) out.push(`"${A.s}" × "${B.s}"`);
      }
      return out;
    }, t);
    if (hits.length) found.push([t, hits]);
  }
  for (const [t, hs] of found) console.log(`${t.toFixed(2)} s: ${hs.slice(0, 4).join("; ")}`);
  console.log(`text check: ${found.length} frames with overlapping text (step ${step} s)`);
  await page.close();
  return found.length;
}

let bad = 0;
if (args.stills) await stills(String(args.stills).split(",").map(Number));
if (args.every) {
  const ts = [];
  for (let t = Number(args.from || 0); t < Number(args.to || film.duration); t += Number(args.every)) ts.push(t);
  await stills(ts);
}
if (args.video) await video();
if (args.textcheck) bad = await textcheck();
await browser.close();
server.close();
process.exit(bad ? 1 : 0);
