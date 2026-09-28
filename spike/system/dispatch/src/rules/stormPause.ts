import { latestReading } from "../db/weatherReadings.js";

/** Rebalancing pauses while the latest Skyglass severity is at least this value. */
export const STORM_SEVERITY = 3;

/** A reading older than this many minutes is stale and does not pause rebalancing. */
export const MAX_READING_AGE_MINUTES = 60;

/**
 * True while the latest Skyglass severity is 3 or more and that reading is
 * no more than 60 minutes old. Consulted only by the nightly-rebalance job;
 * the maintenance sweep keeps running in a storm.
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
