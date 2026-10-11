import scenario from "../../../scenarios/ucsc-music-center.json";
import type { FuelKind } from "./types";
export { scenario };
export const width = scenario.columns * scenario.cellMeters;
export const depth = scenario.rows * scenario.cellMeters;
export function elevation(x: number, z: number) {
  return (
    8 +
    (depth / 2 - z) * 0.105 +
    5 * Math.sin(x / 63) * Math.cos(z / 54) -
    6 * Math.exp(-(((x + 35) / 27) ** 2))
  );
}
export function forestEdge(x: number) {
  return -4 + 15 * Math.sin(x / 57);
}
export function fuelKind(x: number, z: number): FuelKind {
  if (Math.abs(z - scenario.road.z) < scenario.road.width / 2) return "cleared";
  if (
    scenario.buildings.some(
      (b) =>
        Math.abs(x - b.x) < b.width / 2 + 7 &&
        Math.abs(z - b.z) < b.depth / 2 + 7,
    )
  )
    return "cleared";
  if (z < forestEdge(x)) return "forest";
  if (x < -65 && z < 65) return "scrub";
  return "grass";
}
export function cellAt(x: number, z: number) {
  const col = Math.floor((x + width / 2) / scenario.cellMeters);
  const row = Math.floor((z + depth / 2) / scenario.cellMeters);
  return col < 0 || row < 0 || col >= scenario.columns || row >= scenario.rows
    ? -1
    : row * scenario.columns + col;
}
