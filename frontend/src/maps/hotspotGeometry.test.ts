import { describe, expect, it } from 'vitest';
import { hotspotOutline } from './hotspotGeometry';
import type { Hotspot } from '../types/api';

describe('exact hotspot member visualization', () => {
  it('highlights only backend member cells and cancels their internal border', () => {
    const hotspot: Hotspot = { hotspot_id: 'day-01-hotspot-001', lead_day: 1, number_of_cells: 2,
      centroid_latitude: 20, centroid_longitude: 76.125, mean_bust_probability: .7,
      max_bust_probability: .8, mean_confidence: 30,
      bounding_box: { south: 20, north: 20, west: 76, east: 76.25 },
      member_cells: [{ latitude: 20, longitude: 76 }, { latitude: 20, longitude: 76.25 }] };
    const outline = hotspotOutline(hotspot, .25, .25);
    expect(outline).toHaveLength(6);
    expect(outline.some(segment => segment.every(point => point[1] === 76.125))).toBe(false);
    const clipped = hotspotOutline(hotspot, .25, .25, { south: 20, north: 24, west: 76, east: 80 });
    expect(clipped).toHaveLength(6);
    expect(clipped.flat().every(([latitude, longitude]) => latitude >= 20 && latitude <= 24 &&
      longitude >= 76 && longitude <= 80)).toBe(true);
    expect(hotspot.member_cells).toHaveLength(2);
  });
});
