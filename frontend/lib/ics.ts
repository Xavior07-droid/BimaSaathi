// Builds a calendar file (.ics) on the phone for the renewal date (F22). No server call is needed,
// so it also works with the mock layer and without sign-in headers (a plain download link cannot send the token).
// All-day event with alarms at 30/15/7/1 days before.
import { REMINDER_DAYS } from './renewal';
import { formatInr } from './format';

const esc = (s: string) => s.replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
const compact = (iso: string) => iso.replace(/-/g, '');

function nextDay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10).replace(/-/g, '');
}

export function buildIcs(opts: { policyId: string; policyName: string; renewalDate: string; premium: number | null; title: string; note: string }): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  const desc = [opts.note, opts.premium !== null ? formatInr(opts.premium) : ''].filter(Boolean).join(' ');
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//BimaSaathi//Renewal//EN',
    'CALSCALE:GREGORIAN',
    'BEGIN:VEVENT',
    `UID:renewal-${esc(opts.policyId)}-${compact(opts.renewalDate)}@bimasaathi`,
    `DTSTAMP:${stamp}`,
    `DTSTART;VALUE=DATE:${compact(opts.renewalDate)}`,
    `DTEND;VALUE=DATE:${nextDay(opts.renewalDate)}`,
    `SUMMARY:${esc(`${opts.title}: ${opts.policyName}`)}`,
    `DESCRIPTION:${esc(desc)}`,
    ...REMINDER_DAYS.flatMap((d) => ['BEGIN:VALARM', 'ACTION:DISPLAY', `DESCRIPTION:${esc(opts.title)}`, `TRIGGER:-P${d}D`, 'END:VALARM']),
    'END:VEVENT',
    'END:VCALENDAR',
  ];
  return lines.join('\r\n') + '\r\n';
}

export function downloadIcs(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/calendar;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
