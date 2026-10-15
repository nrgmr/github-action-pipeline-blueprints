// Throwaway module for the coverage gate demo. Half of it is tested on purpose.
export function covered(value: number): number {
  const doubled = value * 2;
  return doubled + 1;
}

export function uncovered(value: number): number {
  const tripled = value * 3;
  return tripled + 1;
}
