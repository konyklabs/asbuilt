import { describe, it, expect, beforeEach } from "vitest";
import { onRideEvent, demandForStation, resetDemand } from "../src/consumers/rideEvents.js";

describe("rideEvents", () => {
  beforeEach(() => {
    resetDemand();
  });

  it("counts ride.completed toward the return station's demand", () => {
    onRideEvent({
      rideId: "ride-1",
      riderId: "rider-1",
      bikeId: "bike-1",
      returnStationId: "station-9",
      endedAt: new Date("2026-09-10T09:00:00-04:00"),
      amountCents: 450,
    });
    onRideEvent({
      rideId: "ride-2",
      riderId: "rider-2",
      bikeId: "bike-2",
      returnStationId: "station-9",
      endedAt: new Date("2026-09-10T09:10:00-04:00"),
      amountCents: 300,
    });

    expect(demandForStation("station-9")).toBe(2);
  });
});
