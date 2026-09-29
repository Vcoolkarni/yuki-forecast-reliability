import type { Hotspot } from '../types/api';

export type Segment = [[number, number], [number, number]];

/** Edges shared by adjacent original member cells cancel, leaving the component outline. */
export function hotspotOutline(hotspot: Hotspot, latitudeStep: number, longitudeStep: number,
  domain?: { south: number; north: number; west: number; east: number }): Segment[] {
  const edges = new Map<string, Segment>();
  const add = (start: [number, number], end: [number, number]) => {
    const first = `${start[0].toFixed(6)},${start[1].toFixed(6)}`;
    const second = `${end[0].toFixed(6)},${end[1].toFixed(6)}`;
    const key = [first, second].sort().join('|');
    if (edges.has(key)) edges.delete(key);
    else edges.set(key, [start, end]);
  };
  for (const member of hotspot.member_cells) {
    const south = Math.max(domain?.south ?? -90, member.latitude - latitudeStep / 2);
    const north = Math.min(domain?.north ?? 90, member.latitude + latitudeStep / 2);
    const west = Math.max(domain?.west ?? -180, member.longitude - longitudeStep / 2);
    const east = Math.min(domain?.east ?? 180, member.longitude + longitudeStep / 2);
    add([south, west], [south, east]);
    add([south, east], [north, east]);
    add([north, east], [north, west]);
    add([north, west], [south, west]);
  }
  return [...edges.values()];
}
