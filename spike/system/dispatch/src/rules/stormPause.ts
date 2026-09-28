import { latestReading } from "../db/weatherReadings.js";

/** Compared with >=, not >, against the latest reading's severity. */
export const STORM_SEVERITY = 3;

/** Guards against acting on a reading the weather-poll job hasn't refreshed recently. */
export const MAX_READING_AGE_MINUTES = 60;

/**
 * Looks up the single latest reading on every call; there is no caching,
 * so a burst of calls in the same tick all hit the in-memory store again.
 */
export function isStormPaused(now: Date): boolean {
  const reading = latestReading();
  if (!reading) {
    return false;
  }
  const ageMinutes = (now.getTime() - reading.observedAt.getTime()) / 60000;
  if (ageMinutes > MAX_READING_AGE_MINUTES) {
    return false;
  }
  return reading.severity >= STORM_SEVERITY;
}
