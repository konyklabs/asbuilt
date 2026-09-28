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

/** Opens a maintenance_tickets row of the given kind. */
export function openTicket(bikeId: string, kind: MaintenanceTicketKind, createdAt: Date): MaintenanceTicketRow {
  const row: MaintenanceTicketRow = { id: `mt-${nextId++}`, bikeId, kind, createdAt };
  rows.push(row);
  return row;
}

/** A rider's fault report is stored as a maintenance_tickets row of kind fault_report. */
export function countFaultReports(bikeId: string, since: Date): number {
  return rows.filter((r) => r.bikeId === bikeId && r.kind === "fault_report" && r.createdAt >= since).length;
}
