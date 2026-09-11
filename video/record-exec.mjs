// Record segment 3 only: the execution wake after the human approved the
// expedited option (decision already resolved in the store). Self-triggers
// the wake, watches the button disable/enable, closes on the feed.
import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const RAW = fileURLToPath(new URL('./raw/', import.meta.url));
const browser = await chromium.launch();
const c = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  recordVideo: { dir: RAW, size: { width: 1440, height: 900 } },
});
const p = await c.newPage();
await p.goto('http://localhost:9200', { waitUntil: 'networkidle' });
await p.evaluate(() => document.querySelector('#feed').scrollIntoView({ behavior: 'smooth' }));
await p.waitForTimeout(1500);
await p.evaluate(() => fetch('/api/wake', { method: 'POST' }));
console.log('[3] wake triggered');
await p.waitForFunction(() => document.querySelector('#wake-btn').disabled, undefined, { timeout: 3 * 60 * 1000 });
console.log('[3] execution wake running…');
await p.waitForFunction(() => !document.querySelector('#wake-btn').disabled, undefined, { timeout: 15 * 60 * 1000 });
await p.waitForTimeout(4000);
await p.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
await p.waitForTimeout(3000);
await c.close();
const v = p.video();
await v.saveAs(`${RAW}execution.webm`);
await v.delete().catch(() => {});
await browser.close();
console.log('[3] saved execution.webm');
