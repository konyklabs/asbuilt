import { SkyglassClient } from "../clients/skyglass.js";
import { insertReading } from "../db/weatherReadings.js";

export interface StationLocation {
  id: string;
  lat: number;
  lon: number;
}

export interface WeatherPollDeps {
  skyglass: SkyglassClient;
  stations: () => Promise<StationLocation[]>;
}

/** Sequential, one station at a time; a slow or failing station currently blocks the rest of the batch. */
export async function weatherPoll(deps: WeatherPollDeps): Promise<void> {
  for (const station of await deps.stations()) {
    const reading = await deps.skyglass.fetchSeverity(station.lat, station.lon);
    insertReading({ stationId: station.id, severity: reading.severity, observedAt: reading.observedAt });
  }
}
