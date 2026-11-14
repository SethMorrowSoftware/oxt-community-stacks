// Plays the gallery's stacks in a real browser, and asks a hostile stack
// to break out of its box.
//
//    node tools/tests/browser-check.js <site folder | https://...> [--hostile <slug>] [--limit N]
//
// For a folder it serves the site itself, on 127.0.0.1, with the one
// header GitHub Pages adds to every file (Access-Control-Allow-Origin: *):
// the boxed-in player is a stranger to the site, and gets the engine and
// the stack only because the site hands its files to anyone.
//
// It checks, and prints one "ok" or "FAIL" line for each:
//   - every stack of index.json (or the first N) opens in its play page:
//     the player says "opened", and the frame it plays in has the origin
//     "null", the browser's word for a page boxed in on its own;
//   - the player's page opened on its own, outside a frame, goes back to
//     the gallery and plays nothing;
//   - with --hostile, the stack of that name (tools/tests/test_browser.py
//     makes it) runs JavaScript that tries to read the page around it,
//     the site's storage, cookies and database, and to send the page
//     somewhere else. It must report "BOXED" for each and "BREACH" for
//     none, and what the site kept in storage must still be there.
//
// Exit code 0 when every line is ok, 1 otherwise.
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.wasm': 'application/wasm', '.zip': 'application/zip', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.gif': 'image/gif' };

function serve(folder) {
  const root = path.resolve(folder);
  const server = http.createServer((req, res) => {
    let rel = decodeURIComponent(req.url.split('?')[0]);
    if (rel.endsWith('/')) rel += 'index.html';
    const file = path.join(root, rel);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404, { 'Access-Control-Allow-Origin': '*' });
      res.end('not found');
      return;
    }
    res.writeHead(200, { 'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Access-Control-Allow-Origin': '*' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise(resolve => server.listen(0, '127.0.0.1', () =>
    resolve({ base: 'http://127.0.0.1:' + server.address().port + '/', close: () => server.close() })));
}

let failed = 0;
function result(ok, text) {
  if (!ok) failed++;
  console.log((ok ? 'ok   ' : 'FAIL ') + text);
}

// Opens a stack's play page; resolves with what the player and the stack
// wrote to the console once the player says the stack is open
async function play(browser, base, slug, waitFor) {
  const page = await browser.newPage({ viewport: { width: 1100, height: 800 } });
  const lines = [];
  page.on('console', m => lines.push(m.text()));
  await page.goto(base + 'index.html');
  await page.evaluate(() => {
    localStorage.setItem('canary', 'alive');
    document.cookie = 'canary=alive; path=/';
  });
  await page.goto(base + 's/' + slug + '/play.html');
  const deadline = Date.now() + 120000;
  const done = () => lines.some(l => l.indexOf('PLAYER opened') === 0) &&
    (!waitFor || lines.some(l => l.indexOf(waitFor) === 0));
  while (!done() && Date.now() < deadline) await page.waitForTimeout(250);
  const frames = page.frames().filter(f => f !== page.mainFrame());
  const origin = frames.length ? await frames[0].evaluate(() => self.origin).catch(e => 'error: ' + e) : 'no frame';
  const top = { url: page.url(),
    canary: await page.evaluate(() => [localStorage.getItem('canary'), document.cookie]).catch(e => ['error', String(e)]) };
  await page.close();
  return { lines, opened: lines.some(l => l.indexOf('PLAYER opened') === 0), frames: frames.length, origin, top };
}

(async () => {
  const args = process.argv.slice(2);
  const where = args[0];
  const hostile = args.indexOf('--hostile') >= 0 ? args[args.indexOf('--hostile') + 1] : null;
  const limit = args.indexOf('--limit') >= 0 ? +args[args.indexOf('--limit') + 1] : 0;
  if (!where) { console.error('usage: browser-check.js <site folder | URL> [--hostile <slug>] [--limit N]'); process.exit(2); }
  let server = null, base = where;
  if (!/^https?:/.test(where)) { server = await serve(where); base = server.base; }
  if (!base.endsWith('/')) base += '/';
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const index = await (await page.goto(base + 'index.json')).json();
    await page.goto(base + 'index.html');
    result((await page.locator('#cards .card').count()) === index.stacks.length,
      'the gallery shows ' + index.stacks.length + ' stack(s)');
    await page.close();

    let slugs = index.stacks.map(s => s.slug).filter(s => s !== hostile);
    if (limit) slugs = slugs.slice(0, limit);
    for (const slug of slugs) {
      const r = await play(browser, base, slug);
      result(r.opened, slug + ': the stack opens in the player');
      result(r.frames === 1 && r.origin === 'null', slug + ': it plays boxed in (origin ' + r.origin + ')');
    }

    if (index.stacks.length) {
      const first = index.stacks[0];
      const direct = await browser.newPage();
      const lines = [];
      direct.on('console', m => lines.push(m.text()));
      await direct.goto(base + 'player/play/index.html?stack=../../' + first.download);
      await direct.waitForTimeout(4000);
      result(direct.url().replace(/index\.html$/, '') === base, 'the player opened on its own goes back to the gallery');
      result(!lines.some(l => l.indexOf('PLAYER') === 0), 'and plays nothing there');
      await direct.close();
    }

    if (hostile) {
      const r = await play(browser, base, hostile, 'HOSTILE ');
      const line = r.lines.filter(l => l.indexOf('HOSTILE ') === 0)[0] || '';
      result(r.opened && line !== '', hostile + ': the hostile stack ran its JavaScript');
      const tries = line.replace('HOSTILE ', '').split('|').filter(Boolean);
      result(tries.length >= 6, hostile + ': it tried ' + tries.length + ' ways out');
      for (const t of tries) result(t.indexOf('BOXED ') === 0, hostile + ': ' + t);
      result(r.origin === 'null', hostile + ': it played boxed in (origin ' + r.origin + ')');
      result(r.top.url === base + 's/' + hostile + '/play.html', hostile + ': the page is still the play page');
      result(r.top.canary[0] === 'alive' && r.top.canary[1].indexOf('canary=alive') >= 0,
        hostile + ': the site\'s own storage and cookie are untouched');
    }
  } finally {
    await browser.close();
    if (server) server.close();
  }
  console.log(failed ? failed + ' check(s) FAILED' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
