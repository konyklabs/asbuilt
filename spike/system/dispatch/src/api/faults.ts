import { openTicket } from "../db/maintenanceTickets.js";

export interface FaultReportRequest {
  bikeId: string;
  reportedAt: Date;
}

/** Thin handler: no field validation beyond the TypeScript types, and the write is synchronous. */
export async function postFaultReport(req: FaultReportRequest): Promise<void> {
  openTicket(req.bikeId, "fault_report", req.reportedAt);
}
