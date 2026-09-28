import { describe, it, expect, beforeEach } from "vitest";
import { isStormPaused } from "../src/rules/stormPause.js";
import { resetWeatherReadings, insertReading } from "../src/db/weatherReadings.js";

describe("stormPause", () => {
  beforeEach(() => {
    resetWeatherReadings();
  });

  it("pauses rebalancing while the latest Skyglass severity is 3 or more", () => {
    const now = new Date("2026-09-10T09:00:00-04:00");
    insertReading({ stationId: "station-1", severity: 3, observedAt: now });

    expect(isStormPaused(now)).toBe(true);
  });
});
