import type { Polygon, MultiPolygon } from 'geojson';
import type { GridCell, Hotspot } from '../types/api';
import type { StateBoundaryData } from './StateBoundaries';

export type StateGeometry = Polygon | MultiPolygon;
type Point = [number, number]; // GeoJSON longitude, latitude

export function selectedStateGeometry(data: StateBoundaryData | null, name?: string): StateGeometry | null {
  if (!data || !name) return null;
  const geometry = data.features.find(feature => feature.properties.name === name)?.geometry;
  if (!geometry || (geometry.type !== 'Polygon' && geometry.type !== 'MultiPolygon')) return null;
  return geometry;
}

export function statePolygons(geometry: StateGeometry): Point[][][] {
  return (geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates) as Point[][][];
}

export function stateBounds(geometry: StateGeometry): [[number, number], [number, number]] {
  let south = Infinity, north = -Infinity, west = Infinity, east = -Infinity;
  for (const polygon of statePolygons(geometry)) for (const ring of polygon) for (const [longitude, latitude] of ring) {
    south = Math.min(south, latitude); north = Math.max(north, latitude);
    west = Math.min(west, longitude); east = Math.max(east, longitude);
  }
  if (![south, north, west, east].every(Number.isFinite)) throw new Error('State polygon has no valid coordinates');
  return [[south, west], [north, east]];
}

function onSegment(point: Point, a: Point, b: Point): boolean {
  const cross = (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (b[0] - a[0]);
  return Math.abs(cross) < 1e-10 && point[0] >= Math.min(a[0], b[0]) - 1e-10 &&
    point[0] <= Math.max(a[0], b[0]) + 1e-10 && point[1] >= Math.min(a[1], b[1]) - 1e-10 &&
    point[1] <= Math.max(a[1], b[1]) + 1e-10;
}

function inRing(point: Point, ring: Point[]): boolean {
  let inside = false;
  for (let index = 0; index < ring.length; index++) {
    const a = ring[index], b = ring[(index + 1) % ring.length];
    if (onSegment(point, a, b)) return true;
    if ((a[1] > point[1]) !== (b[1] > point[1]) &&
        point[0] < a[0] + (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1])) inside = !inside;
  }
  return inside;
}

/** Exact polygon membership for source grid centers; holes remain excluded. */
export function insideState(geometry: StateGeometry, latitude: number, longitude: number): boolean {
  const point: Point = [longitude, latitude];
  return statePolygons(geometry).some(rings => inRing(point, rings[0]) &&
    !rings.slice(1).some(hole => inRing(point, hole)));
}

export function stateCells<T extends { latitude: number; longitude: number }>(cells: T[], geometry: StateGeometry): T[] {
  return cells.filter(cell => insideState(geometry, cell.latitude, cell.longitude));
}

/** Pick an existing grid center only when the pointer lies within its half-cell footprint. */
export function nearestStateCell<T extends { latitude: number; longitude: number }>(cells: T[],
  latitude: number, longitude: number, latitudeStep: number, longitudeStep: number): T | null {
  let nearest: T | null = null;
  let distance = Infinity;
  for (const cell of cells) {
    const next = (cell.latitude - latitude) ** 2 + (cell.longitude - longitude) ** 2;
    if (next < distance) { nearest = cell; distance = next; }
  }
  return nearest && distance <= (latitudeStep / 2) ** 2 + (longitudeStep / 2) ** 2 ? nearest : null;
}

/** Show original hotspot intersections only; summary values use original prediction cells. */
export function stateHotspots(hotspots: Hotspot[], cells: GridCell[], geometry: StateGeometry): Hotspot[] {
  const lookup = new Map(cells.map(cell => [`${cell.latitude}|${cell.longitude}`, cell]));
  return hotspots.flatMap(hotspot => {
    const members = hotspot.member_cells.filter(cell => insideState(geometry, cell.latitude, cell.longitude));
    if (!members.length) return [];
    const original = members.map(cell => lookup.get(`${cell.latitude}|${cell.longitude}`)).filter((cell): cell is GridCell => !!cell);
    if (original.length !== members.length) throw new Error('Hotspot member is missing from original forecast grid');
    return [{ ...hotspot, member_cells: members, number_of_cells: members.length,
      centroid_latitude: members.reduce((sum, item) => sum + item.latitude, 0) / members.length,
      centroid_longitude: members.reduce((sum, item) => sum + item.longitude, 0) / members.length,
      mean_bust_probability: original.reduce((sum, item) => sum + item.bust_probability, 0) / original.length,
      max_bust_probability: Math.max(...original.map(item => item.bust_probability)),
      mean_confidence: original.reduce((sum, item) => sum + item.confidence_score, 0) / original.length,
      bounding_box: { south: Math.min(...members.map(item => item.latitude)),
        north: Math.max(...members.map(item => item.latitude)), west: Math.min(...members.map(item => item.longitude)),
        east: Math.max(...members.map(item => item.longitude)) } }];
  });
}
