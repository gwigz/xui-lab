export function shouldInvalidateInspectorState(
  cachedVersion: number | undefined,
  eventVersion: number,
  reset: boolean,
): boolean {
  return reset || cachedVersion === undefined || eventVersion > cachedVersion;
}
