const flags = new Map<string, boolean>();

export function resetFlags(): void {
  flags.clear();
}

export function setFlag(name: string, enabled: boolean): void {
  flags.set(name, enabled);
}

/** Plain Map lookup; a missing key falls through to false via the nullish-coalescing default. */
export function isEnabled(name: string): boolean {
  return flags.get(name) ?? false;
}
