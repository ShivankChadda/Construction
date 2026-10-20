// Motion helpers for the web engines (Chaupal, GSAP scenes): the JavaScript copy of tools/motion.py.
// Same numbers to 1e-9; `python3 tools/motion.py test` checks it. See playbook/MOTION.md and lesson L75.
//
//   import { spring, springs, PRESETS, logZoom } from '../../../tools/motion.mjs';
//   const [f, z] = PRESETS.snappy;
//   el.style.transform = `translateY(${(1 - spring(t - T.w('gravity'), f, z)) * 40}px)`;
//
// Every value is a pure function of t (L15): no timers, no CSS transitions, no state kept between frames.

const TWO_PI = 2 * Math.PI;
const EPS = 1e-4;

export const PRESETS = {
  snappy: [2.85, 0.84],   // labels, plates, UI: overshoots under 1 %
  default: [2.08, 1.0],   // camera, containers: no overshoot
  heavy: [1.74, 1.1],     // big type, whole sheets: creeps in
  playful: [2.14, 0.45],  // characters and props in a warm style only: 21 % overshoot
};

export function settleTime(f = 2.85, zeta = 0.84, eps = EPS) {
  const w = TWO_PI * f;
  if (zeta < 1 - 1e-4) return Math.log(1 / (eps * Math.sqrt(1 - zeta * zeta))) / (zeta * w);
  if (zeta <= 1 + 1e-4) {
    let tau = Math.log(1 / eps) / w;
    for (let i = 0; i < 30; i++) tau = Math.log((1 + w * tau) / eps) / w;
    return tau;
  }
  const s = Math.sqrt(zeta * zeta - 1), r1 = -w * (zeta - s), r2 = -w * (zeta + s);
  return Math.log((Math.abs(r1) + Math.abs(r2)) / ((r1 - r2) * eps)) / Math.abs(r1);
}

// Step response 0 -> 1 at tau seconds after the step; exactly 0 before it and exactly 1 once settled.
export function spring(tau, f = 2.85, zeta = 0.84) {
  if (tau <= 0) return 0;
  if (tau >= settleTime(f, zeta)) return 1;
  const w = TWO_PI * f;
  if (zeta < 1 - 1e-4) {
    const wd = w * Math.sqrt(1 - zeta * zeta);
    return 1 - Math.exp(-zeta * w * tau) * (Math.cos(wd * tau) + (zeta * w / wd) * Math.sin(wd * tau));
  }
  if (zeta <= 1 + 1e-4) return 1 - Math.exp(-w * tau) * (1 + w * tau);
  const s = Math.sqrt(zeta * zeta - 1), r1 = -w * (zeta - s), r2 = -w * (zeta + s);
  return 1 + (r2 * Math.exp(r1 * tau) - r1 * Math.exp(r2 * tau)) / (r1 - r2);
}

// A value sent to new targets over time: changes = [[t0, target], ...] in time order.
export function springs(t, base, changes, f = 2.85, zeta = 0.84) {
  let v = base, prev = base;
  for (const [t0, to] of changes) { v += (to - prev) * spring(t - t0, f, zeta); prev = to; }
  return v;
}

// Zoom from z0 to z1 at eased progress u: the eye reads zoom as a ratio, so interpolate its logarithm.
export function logZoom(u, z0, z1) {
  return z0 * Math.pow(z1 / z0, u);
}

// How far apart each assembly of a machine is at t: {name: share}, 0 assembled, 1 apart (MOTION.md M9). order:
// outside first. opens/closes: the first start (each next `stagger` s later; closing in the reverse order) or a
// start time for each. Only springs that do not overshoot: an overshoot on the way home sinks a part into its mount.
export function explode(t, order, opens, closes = null, stagger = 0.15, f = 2.08, zeta = 1.0) {
  if (zeta < 1) throw new Error('explode needs a spring that does not overshoot (zeta >= 1)');
  const n = order.length;
  const tOpen = Array.isArray(opens) ? opens : order.map((_, i) => opens + i * stagger);
  const tClose = closes === null ? null : Array.isArray(closes) ? closes : order.map((_, i) => closes + (n - 1 - i) * stagger);
  const out = {};
  order.forEach((name, i) => {
    const ch = [[tOpen[i], 1.0]];
    if (tClose) ch.push([tClose[i], 0.0]);
    out[name] = springs(t, 0.0, ch, f, zeta);
  });
  return out;
}
