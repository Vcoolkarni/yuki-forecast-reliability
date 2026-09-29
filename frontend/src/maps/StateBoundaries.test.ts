import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('bundled state boundaries', () => {
  it('contains the requested sourced states and label points in the Central India view', () => {
    const path = resolve(process.cwd(), 'public/data/central-india-states.geojson');
    const source = JSON.parse(readFileSync(path, 'utf-8'));
    const names = source.features.map((item: { properties: { name: string } }) => item.properties.name);
    expect(names).toEqual(expect.arrayContaining(['Madhya Pradesh', 'Maharashtra', 'Rajasthan',
      'Uttar Pradesh', 'Chhattisgarh']));
    expect(source.features).toHaveLength(6);
    for (const item of source.features) {
      expect(item.geometry.type).toMatch(/Polygon/);
      expect(item.properties.labelLatitude).toBeGreaterThanOrEqual(19.5);
      expect(item.properties.labelLatitude).toBeLessThanOrEqual(24.5);
      expect(item.properties.labelLongitude).toBeGreaterThanOrEqual(75.5);
      expect(item.properties.labelLongitude).toBeLessThanOrEqual(80.5);
    }
  });
});
