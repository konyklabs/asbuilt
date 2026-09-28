import type { FetchLike } from "../config.js";

export class FareboxClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike,
  ) {}

  /** Asks farebox to close lost rides through POST /internal/rides/close-lost. */
  async closeLostRides(): Promise<void> {
    await this.fetchImpl(`${this.baseUrl}/internal/rides/close-lost`, { method: "POST" });
  }
}
