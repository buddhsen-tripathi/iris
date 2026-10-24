import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { resolve } from 'node:path';

/** Only the curated media filenames are exposed; video seeking uses HTTP byte ranges. */
export function creatorMediaMiddleware(directory: string) {
  return async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const path = (req.url ?? '').split('?')[0];
    if (!path.startsWith('/creator-media/')) return next();
    const match = /^\/creator-media\/([A-Za-z0-9_-]{11})\/(clip\.mp4|poster\.jpg|captions\.vtt)$/.exec(path);
    if (!match) { res.writeHead(404).end(); return; }
    if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405, { Allow: 'GET, HEAD' }).end(); return; }
    const [, id, file] = match;
    const location = resolve(directory, id, `${id}.${file}`);
    try {
      const { size } = await stat(location);
      let start = 0;
      let end = size - 1;
      const range = req.headers.range;
      if (range) {
        const bytes = /^bytes=(\d*)-(\d*)$/.exec(range);
        if (!bytes || (!bytes[1] && !bytes[2])) { res.writeHead(416, { 'Content-Range': `bytes */${size}` }).end(); return; }
        start = bytes[1] ? Number(bytes[1]) : Math.max(0, size - Number(bytes[2]));
        end = bytes[1] && bytes[2] ? Math.min(Number(bytes[2]), size - 1) : size - 1;
        if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= size) {
          res.writeHead(416, { 'Content-Range': `bytes */${size}` }).end(); return;
        }
      }
      res.writeHead(range ? 206 : 200, {
        'Content-Type': file.endsWith('.mp4') ? 'video/mp4' : file.endsWith('.jpg') ? 'image/jpeg' : 'text/vtt; charset=utf-8',
        'Content-Length': end - start + 1,
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'public, max-age=3600',
        'X-Content-Type-Options': 'nosniff',
        ...(range ? { 'Content-Range': `bytes ${start}-${end}/${size}` } : {}),
      });
      if (req.method === 'HEAD') { res.end(); return; }
      const stream = createReadStream(location, { start, end });
      stream.on('error', () => res.destroy());
      res.on('close', () => stream.destroy());
      stream.pipe(res);
    } catch {
      res.writeHead(404).end('This local clip is unavailable. Open the original video on YouTube.');
    }
  };
}
