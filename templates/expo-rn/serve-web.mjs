// Static server for the Expo web export (`dist/`), honoring $PORT — so ADF's
// AppRunner can serve the cross-platform app on web for the live preview + the
// headless render gate, with NO extra dependency (node stdlib only). SPA fallback
// to index.html so client routing works.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, extname, normalize } from 'node:path';

const DIST = join(process.cwd(), 'dist');
const PORT = Number(process.env.PORT || 8081);
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.ttf': 'font/ttf',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

http
  .createServer(async (req, res) => {
    try {
      let p = decodeURIComponent((req.url || '/').split('?')[0]);
      if (p === '/' || p.endsWith('/')) p += 'index.html';
      let file = normalize(join(DIST, p));
      if (!file.startsWith(DIST)) {
        res.writeHead(403);
        return res.end('forbidden');
      }
      let body;
      try {
        body = await readFile(file);
      } catch {
        file = join(DIST, 'index.html'); // SPA fallback
        body = await readFile(file);
      }
      res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream' });
      res.end(body);
    } catch (e) {
      res.writeHead(500);
      res.end(String(e));
    }
  })
  .listen(PORT, '127.0.0.1', () => console.log(`expo-web served on http://127.0.0.1:${PORT}`));
