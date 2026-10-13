// Display formatting rules (spec section 7): western digits with Indian grouping
// (2,00,000) and dates as DD MMM YYYY. Values come from code, never from the LLM.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** 200000 -> "2,00,000" (always western digits, whatever the UI language). */
export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n);
}

/** 200000 -> "₹2,00,000" */
export function formatInr(n: number | null | undefined): string {
  const s = formatNumber(n);
  return s === '—' ? s : `₹${s}`;
}

/** "2026-03-05" -> "05 Mar 2026". Parses the ISO string directly (no timezone shifts). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return '—';
  const month = MONTHS[Number(m[2]) - 1];
  return month ? `${m[3]} ${month} ${m[1]}` : '—';
}
