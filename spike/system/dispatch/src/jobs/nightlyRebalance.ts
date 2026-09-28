import { isStormPaused } from "../rules/stormPause.js";
import { insertRebalanceOrder } from "../db/rebalanceOrders.js";

export const LOW_FILL = 0.2;
export const HIGH_FILL = 0.9;

/** A rebalance order moves enough bikes to bring the station to 50% full. */
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

/** A station under 20% or over 90% full gets a rebalance order. */
export function needsRebalance(fillRatio: number): boolean {
  return fillRatio < LOW_FILL || fillRatio > HIGH_FILL;
}

/**
 * Plans a rebalance order for every station under 20% or over 90% full,
 * unless the storm pause is in effect, in which case it plans none.
 */
export async function nightlyRebalance(deps: NightlyRebalanceDeps): Promise<RebalancePlan[]> {
  const now = deps.now();
  if (isStormPaused(now)) {
    return [];
  }
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
