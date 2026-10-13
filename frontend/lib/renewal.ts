// Renewal date maths (F22). All in code, from the ISO renewal date: never from the LLM.
// Uses UTC midnight for both dates so time zones and daylight saving cannot shift the count.
import type { IsoDate, ReminderStatus } from './types';

export const REMINDER_DAYS = [30, 15, 7, 1] as const; // spec: reminders at 30/15/7/1 days

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY_MS = 86_400_000;

function toUtcMs(iso: string): number | null {
  const m = ISO.exec(iso);
  if (!m) return null;
  const ms = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const d = new Date(ms);
  // reject impossible dates like 2026-02-31
  return d.getUTCFullYear() === Number(m[1]) && d.getUTCMonth() === Number(m[2]) - 1 && d.getUTCDate() === Number(m[3]) ? ms : null;
}

export const isRealIsoDate = (s: string): boolean => toUtcMs(s) !== null;

/** Today's calendar date in the user's own time zone, as UTC midnight. */
export function todayUtcMs(now: Date = new Date()): number {
  return Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
}

/** Whole days from today to the renewal date (negative = already past). null if no valid date. */
export function daysUntil(iso: IsoDate | null, now: Date = new Date()): number | null {
  if (!iso) return null;
  const ms = toUtcMs(iso);
  return ms === null ? null : Math.round((ms - todayUtcMs(now)) / DAY_MS);
}

/** expired = date has passed; due_soon = within the first reminder window (30 days); else upcoming. */
export function renewalStatus(days: number | null): ReminderStatus | 'no_date' {
  if (days === null) return 'no_date';
  if (days < 0) return 'expired';
  return days <= REMINDER_DAYS[0] ? 'due_soon' : 'upcoming';
}

/** The next reminder day (30/15/7/1) that is still ahead and not sent yet, with its calendar date. */
export function nextReminder(iso: IsoDate | null, sent: number[], now: Date = new Date()): { daysBefore: number; date: IsoDate } | null {
  const ms = iso ? toUtcMs(iso) : null;
  if (ms === null) return null;
  const today = todayUtcMs(now);
  for (const d of REMINDER_DAYS) {
    const at = ms - d * DAY_MS;
    if (at >= today && !sent.includes(d)) {
      return { daysBefore: d, date: new Date(at).toISOString().slice(0, 10) };
    }
  }
  return null;
}
