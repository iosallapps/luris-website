// Accessibility and hygiene checks Lighthouse does not cover, per page, width and theme:
//   - axe-core with the WCAG 2.0/2.1/2.2 A and AA rules plus best practices
//   - requests: every one same-origin, none failing; console and page errors
//   - no horizontal scroll at 320 px (WCAG 1.4.10 reflow)
//   - WCAG 2.4.11: tabbing through the page, no focused element is hidden under the
//     sticky header
//   - cumulative layout shift while scrolling through
//
//   AXE=~/Developer/Pdfino-Website/node_modules/axe-core/axe.min.js node _tools/audit.mjs
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { serve } from './shoot.mjs';

const require = createRequire(path.join(process.env.HOME, 'Developer/ASO/Pdfino/3-pipeline/'));
const puppeteer = require('puppeteer-core');
const AXE = fs.readFileSync(process.env.AXE || path.join(process.env.HOME, 'Developer/Pdfino-Website/node_modules/axe-core/axe.min.js'), 'utf8');

const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await puppeteer.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
let problems = 0;

for (const name of ['index', 'support', 'privacy', 'terms', '404']) {
    const url = `${base}/${name === '404' ? 'missing-page' : name + '.html'}`;
    for (const [width, theme] of [[390, 'light'], [390, 'dark'], [1440, 'light'], [1440, 'dark'], [320, 'light']]) {
        const page = await browser.newPage();
        const requests = [];
        const errors = [];
        page.on('response', (r) => requests.push({ url: r.url(), status: r.status() }));
        page.on('requestfailed', (r) => errors.push(`request failed: ${r.url()}`));
        page.on('console', (m) => {
            // the 404 page is itself served with status 404, which Chrome logs; nothing else may
            const own404 = name === '404' && m.location()?.url === url;
            if (['error', 'warn'].includes(m.type()) && !own404) errors.push(`console ${m.type()}: ${m.text()}`);
        });
        page.on('pageerror', (e) => errors.push(`page error: ${e.message}`));
        await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }]);
        await page.setViewport({ width, height: width === 1440 ? 900 : 780, deviceScaleFactor: 1 });
        await page.evaluateOnNewDocument(() => {
            window.__cls = 0;
            new PerformanceObserver((list) => { for (const e of list.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })
                .observe({ type: 'layout-shift', buffered: true });
        });
        await page.goto(url, { waitUntil: 'networkidle0' });
        await page.evaluate(async () => {
            for (let y = 0; y < document.body.scrollHeight; y += 500) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 40)); }
            window.scrollTo(0, 0);
        });
        await new Promise((r) => setTimeout(r, 300));
        const cls = await page.evaluate(() => window.__cls);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

        // keyboard: every focus stop must be visible below the sticky header
        const hidden = [];
        if (width !== 320) {
            const stops = await page.evaluate(() => document.querySelectorAll('a[href], summary, button').length);
            for (let i = 0; i < stops + 2; i += 1) {
                await page.keyboard.press('Tab');
                const info = await page.evaluate(() => {
                    const el = document.activeElement;
                    if (!el || el === document.body || el.classList.contains('skip-link')) return null;
                    const header = document.querySelector('.site-header').getBoundingClientRect();
                    const r = el.getBoundingClientRect();
                    const inHeader = el.closest('.site-header');
                    return { label: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 40), top: r.top, bottom: r.bottom, headerBottom: header.bottom, inHeader: !!inHeader, h: window.innerHeight };
                });
                if (info && !info.inHeader && (info.bottom <= info.headerBottom || info.top >= info.h)) hidden.push(`${info.label} (top ${Math.round(info.top)})`);
            }
        }

        await page.setBypassCSP(true);
        await page.reload({ waitUntil: 'networkidle0' });
        await page.addScriptTag({ content: AXE });
        const axe = await page.evaluate(async () => {
            const result = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] } });
            return result.violations.map((v) => `${v.impact} ${v.id}: ${v.help} -> ${v.nodes.map((n) => n.target.join(' ')).slice(0, 4).join(' | ')}`);
        });

        const external = requests.filter((r) => !r.url.startsWith(base));
        const failed = requests.filter((r) => r.status >= 400 && !(name === '404' && r.url === url));
        const issues = [
            ...errors, ...external.map((r) => `external request ${r.url}`), ...failed.map((r) => `${r.status} ${r.url}`),
            ...(overflow > 0 ? [`horizontal overflow ${overflow}px`] : []), ...(cls > 0.02 ? [`CLS ${cls.toFixed(3)}`] : []),
            ...hidden.map((h) => `focus hidden: ${h}`), ...axe.map((a) => `axe ${a}`),
        ];
        problems += issues.length;
        console.log(`${name} ${width} ${theme}: ${requests.length} requests, CLS ${cls.toFixed(3)}, ${issues.length ? issues.length + ' issue(s)' : 'clean'}`);
        for (const issue of issues) console.log(`    ${issue}`);
        await page.close();
    }
}
await browser.close();
server.close();
process.exit(problems ? 1 : 0);
