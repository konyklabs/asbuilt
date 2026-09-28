import type { FetchLike } from "../config.js";

export const SKYGLASS_TIMEOUT_MS = 3000;

export interface SeverityReading {
  severity: number;
  observedAt: Date;
}

interface SkyglassSeverityBody {
  severity: number;
  observed_at: string;
}

export class SkyglassClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike,
    private readonly apiKey = "",
  ) {}

  /** GET /v2/severity with the station's latitude and longitude; times out after 3 seconds. */
  async fetchSeverity(lat: number, lon: number): Promise<SeverityReading> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), SKYGLASS_TIMEOUT_MS);
    try {
      const url = `${this.baseUrl}/v2/severity?lat=${lat}&lon=${lon}`;
      const response = await this.fetchImpl(url, {
        headers: this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : undefined,
        signal: controller.signal,
      });
      const body = (await response.json()) as SkyglassSeverityBody;
      return { severity: body.severity, observedAt: new Date(body.observed_at) };
    } finally {
      clearTimeout(timer);
    }
  }
}
