const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');

const BASE = process.env.GF_BASE || 'http://localhost:3000';
const USER = process.env.GF_USER || 'admin';
const PASS = process.env.GF_PASS || 'mecha_change_me';
const OUT_DIR = process.env.SHOTS_DIR || path.join(__dirname, 'shots');

const DASHBOARDS = [
  { uid: 'mecha-overview',    slug: 'mecha-e28094-vue-parc-dbscan',              file: '01_vue_parc.png',  range: 'from=now-30d&to=now' },
  { uid: 'mecha-sensors',     slug: 'mecha-e28094-capteurs-and-anomalies-dbscan', file: '02_capteurs.png',  range: 'from=now-30d&to=now' },
  { uid: 'mecha-api-metrics', slug: 'mecha-e28094-sante-de-l-api',               file: '03_sante_api.png', range: 'from=now-1h&to=now' },
  { uid: 'mecha-demo-live',   slug: 'mecha-e28094-demo-live-dbscan-temps-reel',  file: '04_demo_live.png', range: 'from=now-15m&to=now' },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function forceRender(page) {
  await page.evaluate(async () => {
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    const total = document.body.scrollHeight;
    for (let y = 0; y <= total; y += 400) {
      window.scrollTo(0, y);
      await wait(120);
    }
    window.scrollTo(0, 0);
    await wait(500);
  });
}

async function waitStable(page) {
  let last = -1;
  for (let i = 0; i < 20; i++) {
    const h = await page.evaluate(() => document.querySelector('.react-grid-layout')?.getBoundingClientRect().height || 0);
    if (h === last && h > 0) return h;
    last = h;
    await sleep(500);
  }
  return last;
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1600, height: 2600, deviceScaleFactor: 2 },
  });
  const page = await browser.newPage();

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle2', timeout: 60000 });
  await page.waitForSelector('input[name="user"]', { timeout: 30000 });
  await page.type('input[name="user"]', USER, { delay: 20 });
  await page.type('input[name="password"]', PASS, { delay: 20 });
  await Promise.all([
    page.click('button[type="submit"]'),
    page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 60000 }).catch(() => {}),
  ]);
  await sleep(3000);
  console.log('login done');

  for (const d of DASHBOARDS) {
    const url = `${BASE}/d/${d.uid}/${d.slug}?kiosk&theme=light&${d.range}`;
    try {
      await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
      await sleep(5000);
      await forceRender(page);
      await sleep(3000);

      const bounds = await page.evaluate(() => {
        const grid = document.querySelector('.react-grid-layout');
        if (!grid) return null;
        let minTop = Infinity, maxBottom = 0, minLeft = Infinity, maxRight = 0;
        grid.querySelectorAll('.react-grid-item').forEach((el) => {
          const r = el.getBoundingClientRect();
          minTop = Math.min(minTop, r.top);
          maxBottom = Math.max(maxBottom, r.bottom);
          minLeft = Math.min(minLeft, r.left);
          maxRight = Math.max(maxRight, r.right);
        });
        return { x: minLeft, y: minTop, width: maxRight - minLeft, height: maxBottom - minTop };
      });
      const outPath = path.join(OUT_DIR, d.file);
      if (bounds) {
        const pad = 16;
        const clip = {
          x: Math.max(0, Math.floor(bounds.x - pad)),
          y: Math.max(0, Math.floor(bounds.y - pad)),
          width: Math.ceil(bounds.width + 2 * pad),
          height: Math.ceil(bounds.height + 2 * pad),
        };
        console.log(d.file, 'clip', `${clip.width}x${clip.height} @ (${clip.x},${clip.y})`);
        await page.screenshot({ path: outPath, clip });
      } else {
        console.log(d.file, 'no grid, fullPage fallback');
        await page.screenshot({ path: outPath, fullPage: true });
      }
      console.log('captured', outPath);
    } catch (e) {
      console.error('FAILED', d.file, e.message);
    }
  }

  await browser.close();
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
