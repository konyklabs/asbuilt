import { describe, it, expect, beforeEach, vi } from "vitest";
import { maintenanceSweep } from "../src/jobs/maintenanceSweep.js";
import { resetMaintenanceTickets, openTicket } from "../src/db/maintenanceTickets.js";
import { DockyardClient } from "../src/clients/dockyard.js";
import { FareboxClient } from "../src/clients/farebox.js";
import type { FetchLike, FetchResponse } from "../src/config.js";

function okResponse(body: unknown = {}): FetchResponse {
  return { ok: true, status: 200, json: async () => body };
}

describe("maintenanceSweep", () => {
  beforeEach(() => {
    resetMaintenanceTickets();
  });

  it("locks a bike with 3 fault reports in 7 days and opens a ticket", async () => {
    const now = new Date("2026-09-10T09:00:00-04:00");
    openTicket("bike-1", "fault_report", new Date("2026-09-05T09:00:00-04:00"));
    openTicket("bike-1", "fault_report", new Date("2026-09-07T09:00:00-04:00"));
    openTicket("bike-1", "fault_report", new Date("2026-09-09T09:00:00-04:00"));

    const lockFetch: FetchLike = vi.fn(async () => okResponse());
    const closeLostRidesFetch: FetchLike = vi.fn(async () => okResponse());
    const dockyard = new DockyardClient("http://dockyard.invalid", lockFetch);
    const farebox = new FareboxClient("http://farebox.invalid", closeLostRidesFetch);

    const lockedBikeIds = await maintenanceSweep({
      bikeIds: async () => ["bike-1"],
      dockyard,
      farebox,
      now: () => now,
    });

    expect(lockedBikeIds).toEqual(["bike-1"]);
    expect(lockFetch).toHaveBeenCalledWith(
      "http://dockyard.invalid/bikes/bike-1/lock",
      expect.objectContaining({ method: "POST" }),
    );
    expect(closeLostRidesFetch).toHaveBeenCalledWith(
      "http://farebox.invalid/internal/rides/close-lost",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
