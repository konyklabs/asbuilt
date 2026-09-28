import { insertRebalanceOrder } from "../db/rebalanceOrders.js";

export const LOW_FILL = 0.2;
export const HIGH_FILL = 0.9;

/** Recorded on every order this job inserts; readers use the row, not this constant. */
export const TARGET_FILL = 0.5;

export interface StationFill {
  stationId: string;
  fillRatio: number;
}

export interface RebalancePlan {
  stationId: string;
  targetFill: number;
}

export interface NightlyRebalanceDeps {
  stationFills: () => Promise<StationFill[]>;
  now: () => Date;
}

/** Pure predicate over the two constants above; no I/O, trivial to unit test in isolation. */
export function needsRebalance(fillRatio: number): boolean {
  return fillRatio < LOW_FILL || fillRatio > HIGH_FILL;
}

/**
 * Reads the clock once up front so every order from a single run shares
 * the same timestamp.
 */
export async function nightlyRebalance(deps: NightlyRebalanceDeps): Promise<RebalancePlan[]> {
  const now = deps.now();
  const fills = await deps.stationFills();
  const plans: RebalancePlan[] = [];
  for (const { stationId, fillRatio } of fills) {
    if (needsRebalance(fillRatio)) {
      insertRebalanceOrder(stationId, TARGET_FILL, now);
      plans.push({ stationId, targetFill: TARGET_FILL });
    }
  }
  return plans;
}
