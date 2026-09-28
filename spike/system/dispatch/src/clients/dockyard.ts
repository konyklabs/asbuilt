import type { FetchLike } from "../config.js";

export interface StationFill {
  stationId: string;
  fillRatio: number;
}

export class DockyardClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike,
  ) {}

  /** dispatch locks a bike by calling dockyard's POST /bikes/{id}/lock. */
  async lockBike(bikeId: string): Promise<void> {
    await this.fetchImpl(`${this.baseUrl}/bikes/${bikeId}/lock`, { method: "POST" });
  }

  async stationFills(): Promise<StationFill[]> {
    const response = await this.fetchImpl(`${this.baseUrl}/stations/fills`);
    return (await response.json()) as StationFill[];
  }
}
