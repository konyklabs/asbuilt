import { openTicket } from "../db/maintenanceTickets.js";

export interface FaultReportRequest {
  bikeId: string;
  reportedAt: Date;
}

/** POST /bikes/:id/faults: records a rider's fault report for a bike. */
export async function postFaultReport(req: FaultReportRequest): Promise<void> {
  openTicket(req.bikeId, "fault_report", req.reportedAt);
}
