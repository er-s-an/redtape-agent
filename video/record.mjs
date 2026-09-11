// Record the real demo flow against a fresh RedTape state, in three segments:
//   raw/wake.webm       — dashboard intro + wake + agent working (sped up in post)
//   raw/decision.webm   — decision inbox moment + the human's click (real-time)
//   raw/execution.webm  — execution wake + final feed (sped up in post)
// Usage: node record.mjs   (expects mockgov :9100, redtape :9200, fresh seeded persona)
import { chromium } from 'playwright';
import fs from 'node:fs';

const RAW = new URL('./raw/', import.meta.url).pathname;
fs.rmSync(RAW, { recursive: true, force: true });
fs.mkdirSync(RAW, { recursive: true });

const browser = await chromium.launch();

async function segment(name) {
  const c = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: RAW, size: { width: 1440, height: 900 } },
  });
  const p = await c.newPage();
  return { c, p, async save() { await c.close(); const v = p.video(); await v.saveAs(`${RAW}${name}.webm`); await v.delete().catch(() => {}); } };
}

// --- segment 1: intro + wake ------------------------------------------------
let s = await segment('wake');
await s.p.goto('http://localhost:9200', { waitUntil: 'networkidle' });
await s.p.waitForTimeout(4500);
await s.p.evaluate(() => window.scrollTo({ top: 640, behavior: 'smooth' }));
await s.p.waitForTimeout(2600);
await s.p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
await s.p.waitForTimeout(1500);
await s.p.click('#wake-btn');
console.log('[1] wake started');
await s.p.waitForSelector('.decision', { timeout: 12 * 60 * 1000 });
await s.p.waitForTimeout(1500);
await s.save();
console.log('[1] saved wake.webm');

// --- segment 2: the decision moment (real-time) ------------------------------
s = await segment('decision');
await s.p.goto('http://localhost:9200', { waitUntil: 'networkidle' });
await s.p.evaluate(() => document.querySelector('.decision').scrollIntoView({ behavior: 'smooth', block: 'center' }));
await s.p.waitForTimeout(6000);
await s.p.hover('.decision .opt:nth-child(2)');
await s.p.waitForTimeout(2200);
await s.p.click('.decision .opt');
console.log('[2] resolved with option 1');
await s.p.waitForTimeout(2500);
await s.save();
console.log('[2] saved decision.webm');

// --- segment 3: execution + closing feed -------------------------------------
s = await segment('execution');
await s.p.goto('http://localhost:9200', { waitUntil: 'networkidle' });
await s.p.evaluate(() => document.querySelector('#feed').scrollIntoView({ behavior: 'smooth' }));
console.log('[3] execution wake running…');
await s.p.waitForFunction(() => !document.querySelector('#wake-btn').disabled, { timeout: 12 * 60 * 1000 });
await s.p.waitForTimeout(4000);
await s.p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
await s.p.waitForTimeout(3000);
await s.save();
console.log('[3] saved execution.webm');

await browser.close();
console.log('done → video/raw/');
