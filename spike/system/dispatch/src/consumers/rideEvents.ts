export const CONSUMER_GROUP = "dispatch-demand";

export interface RideCompletedEvent {
  rideId: string;
  riderId: string;
  bikeId: string;
  returnStationId: string;
  endedAt: Date;
  amountCents: number;
}

const demandByStation = new Map<string, number>();

export function resetDemand(): void {
  demandByStation.clear();
}

export function demandForStation(stationId: string): number {
  return demandByStation.get(stationId) ?? 0;
}

/** Counts each ride.completed event toward the demand of the ride's return station. */
export function onRideEvent(event: RideCompletedEvent): void {
  const current = demandByStation.get(event.returnStationId) ?? 0;
  demandByStation.set(event.returnStationId, current + 1);
}
