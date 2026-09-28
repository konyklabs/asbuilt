import { describe, it, expect, beforeEach } from "vitest";
import { isStormPaused } from "../src/rules/stormPause.js";
import { resetWeatherReadings, insertReading } from "../src/db/weatherReadings.js";
import { nightlyRebalance } from "../src/jobs/nightlyRebalance.js";
import { resetRebalanceOrders, listRebalanceOrders } from "../src/db/rebalanceOrders.js";

describe("stormPause", () => {
  beforeEach(() => {
    resetWeatherReadings();
    resetRebalanceOrders();
  });

  it("pauses rebalancing while the latest Skyglass severity is 3 or more", async () => {
    const now = new Date("2026-09-10T09:00:00-04:00");
    const stationFills = async () => [{ stationId: "station-1", fillRatio: 0.1 }];

    insertReading({ stationId: "station-1", severity: 3, observedAt: now });
    expect(isStormPaused(now)).toBe(true);

    const pausedPlans = await nightlyRebalance({ stationFills, now: () => now });
    expect(pausedPlans).toEqual([]);
    expect(listRebalanceOrders()).toHaveLength(0);

    resetWeatherReadings();
    insertReading({ stationId: "station-1", severity: 2, observedAt: now });
    expect(isStormPaused(now)).toBe(false);

    const resumedPlans = await nightlyRebalance({ stationFills, now: () => now });
    expect(resumedPlans).toEqual([{ stationId: "station-1", targetFill: 0.5 }]);
    expect(listRebalanceOrders()).toHaveLength(1);
  });
});
