export type MaintenanceTicketKind = "fault_report" | "maintenance";

export interface MaintenanceTicketRow {
  id: string;
  bikeId: string;
  kind: MaintenanceTicketKind;
  createdAt: Date;
}

const rows: MaintenanceTicketRow[] = [];
let nextId = 1;

export function resetMaintenanceTickets(): void {
  rows.length = 0;
  nextId = 1;
}

/** Appends to an in-memory array; ids are a plain incrementing counter, reset by the helper above. */
export function openTicket(bikeId: string, kind: MaintenanceTicketKind, createdAt: Date): MaintenanceTicketRow {
  const row: MaintenanceTicketRow = { id: `mt-${nextId++}`, bikeId, kind, createdAt };
  rows.push(row);
  return row;
}

/** Linear scan over every row filtered by bike, kind and a cutoff date; would want an index past a handful of bikes. */
export function countFaultReports(bikeId: string, since: Date): number {
  return rows.filter((r) => r.bikeId === bikeId && r.kind === "fault_report" && r.createdAt >= since).length;
}

/** Returns a shallow copy of every row currently in the store, in insertion order. */
export function listTickets(): MaintenanceTicketRow[] {
  return [...rows];
}
