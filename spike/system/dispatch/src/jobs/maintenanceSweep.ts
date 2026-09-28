import { countFaultReports, openTicket } from "../db/maintenanceTickets.js";
import { DockyardClient } from "../clients/dockyard.js";
import { FareboxClient } from "../clients/farebox.js";

export const FAULT_THRESHOLD = 3;
export const FAULT_WINDOW_DAYS = 7;

export interface MaintenanceSweepDeps {
  bikeIds: () => Promise<string[]>;
  dockyard: DockyardClient;
  farebox: FareboxClient;
  now: () => Date;
}

/**
 * A bike with 3 fault reports within 7 days is locked and gets a
 * maintenance ticket. Asks farebox to close lost rides on every run.
 */
export async function maintenanceSweep(deps: MaintenanceSweepDeps): Promise<string[]> {
  const now = deps.now();
  const since = new Date(now.getTime() - FAULT_WINDOW_DAYS * 24 * 60 * 60 * 1000);
  const lockedBikeIds: string[] = [];
  for (const bikeId of await deps.bikeIds()) {
    if (countFaultReports(bikeId, since) >= FAULT_THRESHOLD) {
      openTicket(bikeId, "maintenance", now);
      await deps.dockyard.lockBike(bikeId);
      lockedBikeIds.push(bikeId);
    }
  }
  await deps.farebox.closeLostRides();
  return lockedBikeIds;
}
