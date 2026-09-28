import { describe, it, expect, beforeEach } from "vitest";
import { nightlyRebalance } from "../src/jobs/nightlyRebalance.js";
import { resetRebalanceOrders, listRebalanceOrders } from "../src/db/rebalanceOrders.js";
import { resetWeatherReadings } from "../src/db/weatherReadings.js";

describe("nightlyRebalance", () => {
  beforeEach(() => {
    resetRebalanceOrders();
    resetWeatherReadings();
  });

  it("orders a rebalance for a station under 20% or over 90% full", async () => {
    const now = new Date("2026-09-01T03:00:00-04:00");

    const plans = await nightlyRebalance({
      stationFills: async () => [
        { stationId: "station-low", fillRatio: 0.1 },
        { stationId: "station-high", fillRatio: 0.95 },
        { stationId: "station-mid", fillRatio: 0.5 },
      ],
      now: () => now,
    });

    const stationIds = plans.map((plan) => plan.stationId).sort();
    expect(stationIds).toEqual(["station-high", "station-low"]);
    expect(listRebalanceOrders()).toHaveLength(2);

    resetRebalanceOrders();
    const boundaryPlans = await nightlyRebalance({
      stationFills: async () => [
        { stationId: "station-low-edge", fillRatio: 0.2 },
        { stationId: "station-high-edge", fillRatio: 0.9 },
      ],
      now: () => now,
    });
    expect(boundaryPlans).toEqual([]);
    expect(listRebalanceOrders()).toHaveLength(0);
  });
});
