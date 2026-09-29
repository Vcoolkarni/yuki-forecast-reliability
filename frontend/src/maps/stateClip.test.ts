import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import type { MultiPolygon } from 'geojson';
import type { GridCell, Hotspot } from '../types/api';
import { buildRegularGrid, projectedPixel, renderDisplayRaster } from './raster';
import { insideState, nearestStateCell, selectedStateGeometry, stateBounds, stateCells, stateHotspots } from './stateClip';
import type { StateBoundaryData } from './StateBoundaries';

const islands: MultiPolygon = { type: 'MultiPolygon', coordinates: [
  [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]],
  [[[6, 0], [8, 0], [8, 2], [6, 2], [6, 0]]]
] };

describe('selected-state display filtering', () => {
  it('uses all MultiPolygon islands, excludes holes and outside cells, and preserves source values', () => {
    const cells = [{ latitude: .5, longitude: .5, bust_probability: .2, confidence_score: 80 },
      { latitude: 2, longitude: 2, bust_probability: .9, confidence_score: 10 },
      { latitude: 1, longitude: 7, bust_probability: .7, confidence_score: 30 },
      { latitude: 5, longitude: 5, bust_probability: .4, confidence_score: 60 }] as GridCell[];
    const original = structuredClone(cells);
    expect(stateBounds(islands)).toEqual([[0, 0], [4, 8]]);
    expect(insideState(islands, .5, .5)).toBe(true);
    expect(insideState(islands, 2, 2)).toBe(false); // interior hole
    expect(insideState(islands, 1, 7)).toBe(true); // separate island
    expect(insideState(islands, 5, 5)).toBe(false);
    expect(stateCells(cells, islands).map(cell => cell.longitude)).toEqual([.5, 7]);
    expect(nearestStateCell(stateCells(cells, islands), .55, .55, .5, .5)?.longitude).toBe(.5);
    expect(nearestStateCell(stateCells(cells, islands), 3.9, 3.9, .5, .5)).toBeNull();
    expect(cells).toEqual(original);
  });

  it('retains only the state-intersecting original hotspot cells and recomputes display statistics', () => {
    const cells = [{ latitude: .5, longitude: .5, bust_probability: .2, confidence_score: 80 },
      { latitude: 1, longitude: 7, bust_probability: .7, confidence_score: 30 },
      { latitude: 5, longitude: 5, bust_probability: .9, confidence_score: 10 }] as GridCell[];
    const hotspot = { hotspot_id: 'day-01-hotspot-001', lead_day: 1,
      member_cells: cells.map(cell => ({ latitude: cell.latitude, longitude: cell.longitude })) } as Hotspot;
    const selected = stateHotspots([hotspot], cells, islands);
    expect(selected).toHaveLength(1);
    expect(selected[0].number_of_cells).toBe(2);
    expect(selected[0].mean_bust_probability).toBeCloseTo(.45);
    expect(selected[0].max_bust_probability).toBe(.7);
    expect(selected[0].member_cells.map(cell => cell.longitude)).toEqual([.5, 7]);
    expect(hotspot.member_cells).toHaveLength(3); // no mutation of API hotspot
  });

  it('finds the named geometry in the complete local India asset', () => {
    const data = JSON.parse(readFileSync(resolve(process.cwd(), 'public/data/india-states.geojson'), 'utf-8')) as StateBoundaryData;
    expect(data.features).toHaveLength(36);
    expect(selectedStateGeometry(data, 'Andaman and Nicobar Islands')?.type).toBe('MultiPolygon');
    expect(selectedStateGeometry(data, 'Unknown State')).toBeNull();
    const centers = Array.from({ length: 63 }, (_, row) => Array.from({ length: 61 }, (_, column) =>
      ({ latitude: 6 + row * .5, longitude: 68 + column * .5 }))).flat();
    expect(stateCells(centers, selectedStateGeometry(data, 'Madhya Pradesh')!)).toHaveLength(107);
    for (const name of ['Delhi', 'Chandigarh', 'Lakshadweep', 'Puducherry',
      'Dadra and Nagar Haveli and Daman and Diu']) {
      expect(stateCells(centers, selectedStateGeometry(data, name)!)).toHaveLength(0);
    }
  });

  it('alpha-masks the continuous raster with even-odd holes and separate island paths', () => {
    const grid = buildRegularGrid([{ latitude: 0, longitude: 0, value: 1 },
      { latitude: 0, longitude: 8, value: 2 }, { latitude: 4, longitude: 0, value: 3 },
      { latitude: 4, longitude: 8, value: 4 }]);
    expect(projectedPixel(grid, 4, 0, 8)).toEqual([0, 0]);
    const fill = vi.fn(), drawImage = vi.fn(), putImageData = vi.fn();
    const context = { createImageData: () => ({ data: new Uint8ClampedArray(8 * 8 * 4) }),
      putImageData, beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(),
      fill, drawImage, save: vi.fn(), restore: vi.fn(), globalCompositeOperation: '' };
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
    const toDataURL = vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,masked');
    expect(renderDisplayRaster(grid, 'heat', 8, undefined, islands)).toBe('data:image/png;base64,masked');
    expect(fill).toHaveBeenCalledTimes(2); // both island polygons
    expect(fill).toHaveBeenCalledWith('evenodd'); // interior hole is transparent
    expect(context.globalCompositeOperation).toBe('destination-in');
    expect(drawImage).toHaveBeenCalledOnce();
    expect(putImageData).toHaveBeenCalledOnce();
    getContext.mockRestore(); toDataURL.mockRestore();
  });
});
