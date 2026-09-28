const flags = new Map<string, boolean>();

export function resetFlags(): void {
  flags.clear();
}

export function setFlag(name: string, enabled: boolean): void {
  flags.set(name, enabled);
}

/** Reads feature_flags on every job run. */
export function isEnabled(name: string): boolean {
  return flags.get(name) ?? false;
}
