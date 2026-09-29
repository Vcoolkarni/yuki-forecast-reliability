import { describe, expect, it, vi } from 'vitest';
import { heatRgb } from '../services/format';
import { buildRegularGrid, cellBounds, divergingRgb, renderDisplayRaster, sampleDisplayValue } from './raster';

describe('display-only gridded raster', () => {
  const samples = [
    { latitude: 20, longitude: 76, value: 1 }, { latitude: 20, longitude: 76.25, value: 2 },
    { latitude: 20.25, longitude: 76, value: 3 }, { latitude: 20.25, longitude: 76.25, value: 4 }
  ];
  it('keeps source cells unchanged, preserves lat/lon orientation, and clips to their footprint', () => {
    const before = structuredClone(samples);
    const grid = buildRegularGrid(samples);
    expect(grid.values).toEqual([[1, 2], [3, 4]]);
    expect(grid).toMatchObject({ south: 20, north: 20.25, west: 76, east: 76.25 });
    expect(cellBounds(grid, 20, 76)).toEqual([[20, 76], [20.125, 76.125]]);
    expect(cellBounds(grid, 20.25, 76.25)).toEqual([[20.125, 76.125], [20.25, 76.25]]);
    expect(sampleDisplayValue(grid, 20, 76)).toBe(1);
    expect(sampleDisplayValue(grid, 20.25, 76.25)).toBe(4);
    expect(sampleDisplayValue(grid, 20.125, 76.125)).toBe(2.5);
    expect(samples).toEqual(before);
  });
  it('refuses missing, duplicate, and nonregular source cells rather than inventing values', () => {
    expect(() => buildRegularGrid(samples.slice(1))).toThrow(/complete/);
    expect(() => buildRegularGrid([...samples, samples[0]])).toThrow();
    expect(() => buildRegularGrid([...samples.filter(item => item.latitude === 20),
      { latitude: 20.3, longitude: 76, value: 3 }, { latitude: 20.3, longitude: 76.25, value: 4 },
      { latitude: 20.7, longitude: 76, value: 5 }, { latitude: 20.7, longitude: 76.25, value: 6 }])).toThrow(/regular/);
  });
  it('centers comparison change colors on a neutral zero', () => {
    expect(divergingRgb(0, .3)).toEqual([246, 247, 241]);
    expect(divergingRgb(-.3, .3)).toEqual([54, 137, 248]);
    expect(divergingRgb(.3, .3)).toEqual([245, 79, 74]);
  });
  it('rasterizes north at the top without modifying the source cells', () => {
    const image = { data: new Uint8ClampedArray(16) };
    const put = vi.fn();
    const context = { createImageData: () => image, putImageData: put };
    const getContext = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
    const toDataURL = vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,test');
    const before = structuredClone(samples);
    expect(renderDisplayRaster(buildRegularGrid(samples), 'heat', 2)).toBe('data:image/png;base64,test');
    expect([...image.data.slice(0, 3)]).toEqual(heatRgb(2.75, 1, 4)); // northwest pixel center
    expect([...image.data.slice(8, 11)]).toEqual(heatRgb(1.75, 1, 4)); // southwest pixel center
    expect(samples).toEqual(before);
    expect(put).toHaveBeenCalledOnce();
    getContext.mockRestore(); toDataURL.mockRestore();
  });
});
