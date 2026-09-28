import type { FetchLike } from "../config.js";

export class FareboxClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike,
  ) {}

  /** No request body; the server decides which rides qualify. */
  async closeLostRides(): Promise<void> {
    await this.fetchImpl(`${this.baseUrl}/internal/rides/close-lost`, { method: "POST" });
  }
}
