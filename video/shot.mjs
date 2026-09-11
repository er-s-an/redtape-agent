// Screenshot the RedTape dashboard for design review.
import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
await page.goto('http://localhost:9200', { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
await page.screenshot({ path: process.argv[2] || 'shot.png', fullPage: true });
await browser.close();
console.log('saved', process.argv[2] || 'shot.png');
