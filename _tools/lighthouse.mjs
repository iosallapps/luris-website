// Lighthouse, every page, mobile and desktop, with the Lighthouse 12 install that npx
// already cached on this Mac and the local Google Chrome.
//
//   node _tools/lighthouse.mjs                      local copy, served with gzip like GitHub Pages
//   node _tools/lighthouse.mjs https://lurisapp.com the live site
//
// Prints the four category scores plus LCP, CLS, TBT and transfer size per run, and
// writes the full JSON reports to .preview/lighthouse/.
import { createRequire } from 'node:module';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath, pathToFileURL } from 'node:url';

const NPX = path.join(process.env.HOME, '.npm/_npx/8003d8991b0d346b/node_modules');
const require = createRequire(NPX + '/');
const chromeLauncher = require('chrome-launcher');
const { default: lighthouse, desktopConfig } = await import(pathToFileURL(path.join(NPX, 'lighthouse/core/index.js')).href);
const SITE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(SITE, '.preview', 'lighthouse');
const TYPES = {
    '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.svg': 'image/svg+xml', '.webp': 'image/webp',
    '.avif': 'image/avif', '.png': 'image/png', '.jpg': 'image/jpeg', '.ico': 'image/x-icon',
    '.xml': 'application/xml', '.txt': 'text/plain',
};
const COMPRESS = new Set(['.html', '.css', '.svg', '.xml', '.txt']);

function serve() {
    const server = http.createServer((req, res) => {
        let file = path.join(SITE, decodeURIComponent(req.url.split('?')[0]));
        let status = 200;
        if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
        if (!fs.existsSync(file)) { file = path.join(SITE, '404.html'); status = 404; }
        const ext = path.extname(file);
        const headers = { 'content-type': TYPES[ext] || 'application/octet-stream', 'cache-control': 'max-age=600' };
        let body = fs.readFileSync(file);
        if (COMPRESS.has(ext) && /gzip/.test(req.headers['accept-encoding'] || '')) {
            body = zlib.gzipSync(body);
            headers['content-encoding'] = 'gzip';
        }
        headers['content-length'] = body.length;
        res.writeHead(status, headers);
        res.end(body);
    });
    return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

const live = process.argv[2];
const server = live ? null : await serve();
const base = live ? live.replace(/\/$/, '') : `http://127.0.0.1:${server.address().port}`;
const pages = [['home', '/'], ['support', '/support.html'], ['privacy', '/privacy.html'], ['terms', '/terms.html'], ['404', '/404.html']];
fs.mkdirSync(OUT, { recursive: true });

const chrome = await chromeLauncher.launch({
    chromePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    chromeFlags: ['--headless=new', '--no-first-run'],
});
const rows = [];
try {
    for (const [name, url] of pages) {
        for (const form of ['mobile', 'desktop']) {
            const config = form === 'desktop' ? desktopConfig : undefined;
            const result = await lighthouse(base + url, { port: chrome.port, output: 'json', logLevel: 'error' }, config);
            const lhr = result.lhr;
            fs.writeFileSync(path.join(OUT, `${name}-${form}${live ? '-live' : ''}.json`), result.report);
            const s = (k) => Math.round((lhr.categories[k].score || 0) * 100);
            const a = (k) => lhr.audits[k];
            const failed = Object.values(lhr.audits)
                .filter((x) => x.score !== null && x.score < 1 && ['binary', 'numeric'].includes(x.scoreDisplayMode) && x.details?.type !== 'debugdata')
                .map((x) => x.id);
            rows.push({
                page: name, form,
                perf: s('performance'), a11y: s('accessibility'), bp: s('best-practices'), seo: s('seo'),
                lcp: a('largest-contentful-paint').displayValue, cls: a('cumulative-layout-shift').displayValue,
                tbt: a('total-blocking-time').displayValue, bytes: a('total-byte-weight').displayValue,
                requests: a('network-requests').details?.items?.length,
                notPassing: failed.join(' '),
            });
            console.log(JSON.stringify(rows.at(-1)));
        }
    }
} finally {
    await chrome.kill();
    server?.close();
}
