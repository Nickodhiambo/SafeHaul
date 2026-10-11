/** `<input type="datetime-local">` value for a Date, in the user's local time ("YYYY-MM-DDTHH:mm"). */
export function toLocalInputValue(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Default departure: the start of the next full hour. */
export function defaultDeparture(now: Date = new Date()): string {
  const d = new Date(now);
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  return toLocalInputValue(d);
}

/**
 * Local datetime-local value -> ISO 8601 in UTC ("...Z"), which carries the timezone the
 * backend requires. Returns null for empty/invalid input.
 */
export function toIsoUtc(localValue: string): string | null {
  if (!localValue) return null;
  const d = new Date(localValue);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

const MAX_FORECAST_DAYS = 16;

/** Why a departure can't be analysed, or null if it's fine. */
export function departureProblem(localValue: string, now: Date = new Date()): string | null {
  const iso = toIsoUtc(localValue);
  if (!iso) return "Choose a departure date and time.";
  const t = new Date(iso).getTime();
  if (t < now.getTime() - 60 * 60 * 1000) return "Departure is in the past.";
  if (t > now.getTime() + (MAX_FORECAST_DAYS - 1) * 24 * 60 * 60 * 1000)
    return `Forecasts only cover the next ${MAX_FORECAST_DAYS} days.`;
  return null;
}

const dayTime = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});
const fullDateTime = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

/** "Mon 8:00 AM" in the viewer's timezone. */
export const formatDayTime = (iso: string) => dayTime.format(new Date(iso));
/** "Mon, Oct 12, 8:00 AM" in the viewer's timezone. */
export const formatDateTime = (iso: string) => fullDateTime.format(new Date(iso));

export const addHours = (iso: string, hours: number) =>
  new Date(new Date(iso).getTime() + hours * 3_600_000).toISOString();
