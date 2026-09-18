// Proof renders and the social image, with the puppeteer-core install the ASO
// pipeline already has (read-only there) and the local Google Chrome.
//
//   node _tools/shoot.mjs previews [page ...]  -> .preview/<page>-<width>-<theme>.png
//   node _tools/shoot.mjs og                   -> og-image.jpg (1200x630, from _tools/og.html)
//
// Serves the repo over a local HTTP server so root-relative links, srcset and the
// stylesheet behave as they do on GitHub Pages. Previews are shot at 390, 768 and
// 1440 px in light and dark, with the route line fully drawn (reduced motion) and
// every lazy image loaded. Tall pages are captured in chunks and stitched.
import { createRequire } from 'node:module';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const require = createRequire(path.join(process.env.HOME, 'Developer/ASO/Pdfino/3-pipeline/'));
const puppeteer = require('puppeteer-core');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const SITE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(SITE, '.preview');
const TYPES = {
    '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.svg': 'image/svg+xml', '.webp': 'image/webp',
    '.avif': 'image/avif', '.png': 'image/png', '.jpg': 'image/jpeg', '.ico': 'image/x-icon',
    '.xml': 'application/xml', '.txt': 'text/plain',
};

export function serve() {
    const server = http.createServer((req, res) => {
        let file = path.join(SITE, decodeURIComponent(req.url.split('?')[0]));
        if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
        if (!fs.existsSync(file)) {
            res.writeHead(404, { 'content-type': TYPES['.html'] });
            fs.createReadStream(path.join(SITE, '404.html')).pipe(res);
            return;
        }
        res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'application/octet-stream', 'content-length': fs.statSync(file).size });
        fs.createReadStream(file).pipe(res);
    });
    return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

async function main() {
    const mode = process.argv[2] || 'previews';
    const server = await serve();
    const base = `http://127.0.0.1:${server.address().port}`;
    const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--font-render-hinting=none', '--hide-scrollbars'] });
    try {
        if (mode === 'og') {
            const page = await browser.newPage();
            await page.setViewport({ width: 1200, height: 630, deviceScaleFactor: 1 });
            await page.goto(`${base}/_tools/og.html`, { waitUntil: 'networkidle0' });
            const png = path.join(OUT, 'og.png');
            fs.mkdirSync(OUT, { recursive: true });
            await page.screenshot({ path: png, clip: { x: 0, y: 0, width: 1200, height: 630 } });
            execFileSync('python3', ['-c', `from PIL import Image; Image.open(${JSON.stringify(png)}).convert('RGB').save(${JSON.stringify(path.join(SITE, 'og-image.jpg'))}, 'JPEG', quality=86, optimize=True, progressive=True)`]);
            console.log(`og-image.jpg ${fs.statSync(path.join(SITE, 'og-image.jpg')).size} bytes`);
            return;
        }
        fs.mkdirSync(OUT, { recursive: true });
        const pages = process.argv.slice(3).length ? process.argv.slice(3) : ['index', 'support', 'privacy', 'terms', '404'];
        for (const name of pages) {
            for (const width of [390, 768, 1440]) {
                for (const theme of ['light', 'dark']) {
                    const page = await browser.newPage();
                    const dpr = width === 1440 ? 1 : 2;
                    // the page's CSP forbids inline styles; the proof tool needs one to unstick the header
                    await page.setBypassCSP(true);
                    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: theme }, { name: 'prefers-reduced-motion', value: 'reduce' }]);
                    await page.setViewport({ width, height: width === 390 ? 844 : 900, deviceScaleFactor: dpr });
                    await page.goto(`${base}/${name === '404' ? 'no-such-page' : name + '.html'}`, { waitUntil: 'networkidle0' });
                    await page.$$eval('img', (imgs) => Promise.all(imgs.map((img) => { img.loading = 'eager'; return img.decode().catch(() => {}); })));
                    await new Promise((r) => setTimeout(r, 250));
                    await page.addStyleTag({ content: '.site-header{position:static}' });
                    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
                    const height = await page.evaluate(() => document.documentElement.scrollHeight);
                    const chunk = Math.floor(16000 / dpr);
                    const parts = [];
                    for (let y = 0, part = 0; y < height; y += chunk, part += 1) {
                        const file = path.join(OUT, `${name}-${width}-${theme}.part${part}.png`);
                        await page.screenshot({ path: file, clip: { x: 0, y, width, height: Math.min(chunk, height - y) }, captureBeyondViewport: true });
                        parts.push(file);
                    }
                    const out = path.join(OUT, `${name}-${width}-${theme}.png`);
                    execFileSync('python3', ['-c', `
import sys
from PIL import Image
parts = [Image.open(p) for p in sys.argv[2:]]
w = parts[0].width; h = sum(p.height for p in parts)
sheet = Image.new('RGB', (w, h)); y = 0
for p in parts: sheet.paste(p, (0, y)); y += p.height
sheet.save(sys.argv[1])
`, out, ...parts]);
                    for (const p of parts) fs.unlinkSync(p);
                    console.log(`${name}-${width}-${theme}: ${height}px${overflow > 0 ? `  HORIZONTAL OVERFLOW ${overflow}px` : ''}`);
                    await page.close();
                }
            }
        }
    } finally {
        await browser.close();
        server.close();
    }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
