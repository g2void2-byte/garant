export function isPositiveSafeInteger(value: number | undefined): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export function parsePositiveIntRouteParam(value: string | undefined): number | undefined {
  if (!value || !/^[1-9]\d*$/.test(value)) return undefined;
  const parsed = Number(value);
  return isPositiveSafeInteger(parsed) ? parsed : undefined;
}

export function parsePositiveIntValue(value: unknown): number | undefined {
  if (typeof value === "number") {
    return isPositiveSafeInteger(value) ? value : undefined;
  }
  if (typeof value === "string") return parsePositiveIntRouteParam(value);
  return undefined;
}
