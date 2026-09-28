import { describe, it, expect, beforeEach, vi } from "vitest";
import { maintenanceSweep } from "../src/jobs/maintenanceSweep.js";
import { resetMaintenanceTickets, openTicket, listTickets } from "../src/db/maintenanceTickets.js";
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

    const openedTickets = listTickets().filter((t) => t.bikeId === "bike-1" && t.kind === "maintenance");
    expect(openedTickets).toHaveLength(1);

    resetMaintenanceTickets();
    openTicket("bike-2", "fault_report", new Date("2026-09-05T09:00:00-04:00"));
    openTicket("bike-2", "fault_report", new Date("2026-09-07T09:00:00-04:00"));

    const notLockedWithTwoReports = await maintenanceSweep({
      bikeIds: async () => ["bike-2"],
      dockyard,
      farebox,
      now: () => now,
    });
    expect(notLockedWithTwoReports).toEqual([]);

    resetMaintenanceTickets();
    openTicket("bike-3", "fault_report", new Date("2026-09-03T08:59:00-04:00")); // 7 days and 1 minute before `now`
    openTicket("bike-3", "fault_report", new Date("2026-09-07T09:00:00-04:00"));
    openTicket("bike-3", "fault_report", new Date("2026-09-09T09:00:00-04:00"));

    const notLockedWithStaleReport = await maintenanceSweep({
      bikeIds: async () => ["bike-3"],
      dockyard,
      farebox,
      now: () => now,
    });
    expect(notLockedWithStaleReport).toEqual([]);
  });
});
