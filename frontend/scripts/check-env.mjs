// F27: stops a production build that would ship with mocks on, a localhost API, or missing Firebase keys.
//   npm run build:prod        (runs this, then next build)
// Reads the same files Next.js does for a production build, in the same priority order.
import { existsSync, readFileSync } from 'node:fs';

const files = ['.env.production.local', '.env.local', '.env.production', '.env'];
const fromFiles = {};
for (const f of [...files].reverse()) {
  if (!existsSync(f)) continue;
  for (const line of readFileSync(f, 'utf8').split(/\r?\n/)) {
    const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(line);
    if (m && !line.trim().startsWith('#')) fromFiles[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
  }
}
const get = (k) => process.env[k] ?? fromFiles[k] ?? '';

const problems = [];
if (get('NEXT_PUBLIC_USE_MOCKS') === 'true') problems.push('NEXT_PUBLIC_USE_MOCKS is "true": the app would show sample data. Set it to false.');
const base = get('NEXT_PUBLIC_API_BASE');
if (!base) problems.push('NEXT_PUBLIC_API_BASE is empty. Set it to the Render URL, for example https://bimasaathi-api.onrender.com');
else if (!/^https:\/\//.test(base)) problems.push(`NEXT_PUBLIC_API_BASE must start with https:// (got "${base}"). A https site cannot call an http API.`);
else if (/localhost|127\.0\.0\.1/.test(base)) problems.push('NEXT_PUBLIC_API_BASE points to localhost.');
if (get('NEXT_PUBLIC_DEBUG') === 'true') problems.push('NEXT_PUBLIC_DEBUG is "true": the /debug page would be live in production. Remove it.');
for (const k of ['API_KEY', 'AUTH_DOMAIN', 'PROJECT_ID', 'APP_ID', 'MESSAGING_SENDER_ID', 'VAPID_KEY']) {
  if (!get(`NEXT_PUBLIC_FIREBASE_${k}`)) problems.push(`NEXT_PUBLIC_FIREBASE_${k} is missing.`);
}

if (problems.length) {
  console.error('\nProduction build blocked:\n' + problems.map((p) => `  - ${p}`).join('\n') + '\n');
  process.exit(1);
}
console.log(`Environment looks right for production (API: ${base}).`);
