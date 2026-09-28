export interface FetchInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  signal?: AbortSignal;
}

export interface FetchResponse {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}

/** The shape of fetch every HTTP client takes, so a test can inject a stub. */
export type FetchLike = (input: string, init?: FetchInit) => Promise<FetchResponse>;

export interface Config {
  dockyardBaseUrl: string;
  fareboxBaseUrl: string;
  skyglassBaseUrl: string;
  skyglassApiKey: string;
}

function readEnv(name: string, fallback: string): string {
  return process.env[name] ?? fallback;
}

export const config: Config = {
  dockyardBaseUrl: readEnv("DOCKYARD_BASE_URL", "http://localhost:8001"),
  fareboxBaseUrl: readEnv("FAREBOX_BASE_URL", "http://localhost:8002"),
  skyglassBaseUrl: readEnv("SKYGLASS_BASE_URL", "https://api.skyglass.invalid"),
  skyglassApiKey: readEnv("SKYGLASS_API_KEY", ""),
};
