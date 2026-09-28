export interface WeatherReading {
  stationId: string;
  severity: number;
  observedAt: Date;
}

const readings: WeatherReading[] = [];

export function resetWeatherReadings(): void {
  readings.length = 0;
}

export function insertReading(reading: WeatherReading): void {
  readings.push(reading);
}

export function latestReading(): WeatherReading | null {
  if (readings.length === 0) {
    return null;
  }
  return readings.reduce((latest, r) => (r.observedAt > latest.observedAt ? r : latest));
}
