import { heatRgb } from '../services/format';
import type { Hotspot } from '../types/api';
import { hotspotOutline } from './hotspotGeometry';
import { statePolygons, type StateGeometry } from './stateClip';

export type Sample = { latitude: number; longitude: number; value: number };
export type RegularGrid = { latitudes: number[]; longitudes: number[]; values: number[][];
  south: number; north: number; west: number; east: number; min: number; max: number };
export type RasterPalette = 'heat' | 'confidence' | 'difference';

const mercatorY = (latitude: number) => Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360));
const inverseMercatorY = (value: number) => (2 * Math.atan(Math.exp(value)) - Math.PI / 2) * 180 / Math.PI;

/** Leaflet ImageOverlay is linear in Web Mercator screen coordinates. */
export function projectedPixel(grid: RegularGrid, latitude: number, longitude: number, size: number): [number, number] {
  return [size * (longitude - grid.west) / (grid.east - grid.west),
    size * (mercatorY(grid.north) - mercatorY(latitude)) /
    (mercatorY(grid.north) - mercatorY(grid.south))];
}

/** Alpha-mask the rendered image with all polygon parts and interior holes. */
export function maskRasterToState(canvas: HTMLCanvasElement, grid: RegularGrid, geometry: StateGeometry): void {
  const mask = document.createElement('canvas');
  mask.width = canvas.width; mask.height = canvas.height;
  const maskContext = mask.getContext('2d');
  const context = canvas.getContext('2d');
  if (!maskContext || !context) throw new Error('Canvas masking is unavailable');
  maskContext.fillStyle = '#ffffff';
  for (const polygon of statePolygons(geometry)) {
    maskContext.beginPath();
    for (const ring of polygon) {
      ring.forEach(([longitude, latitude], index) => {
        const [x, y] = projectedPixel(grid, latitude, longitude, canvas.width);
        if (index === 0) maskContext.moveTo(x, y); else maskContext.lineTo(x, y);
      });
      maskContext.closePath();
    }
    maskContext.fill('evenodd');
  }
  context.save();
  context.globalCompositeOperation = 'destination-in';
  context.drawImage(mask, 0, 0);
  context.restore();
}

/** An exact, validated view of the source cells. No new forecast records are made. */
export function buildRegularGrid(samples: Sample[]): RegularGrid {
  if (!samples.length) throw new Error('Cannot render an empty forecast grid');
  const latitudes = [...new Set(samples.map(sample => sample.latitude))].sort((a, b) => a - b);
  const longitudes = [...new Set(samples.map(sample => sample.longitude))].sort((a, b) => a - b);
  if (latitudes.length < 2 || longitudes.length < 2 || latitudes.length * longitudes.length !== samples.length)
    throw new Error('Display raster requires a complete two-dimensional source grid');
  const step = (coords: number[]) => {
    const spacing = coords[1] - coords[0];
    if (!(spacing > 0) || coords.some((coordinate, index) => index > 0 && Math.abs(coordinate - coords[index - 1] - spacing) > 1e-7))
      throw new Error('Display raster requires a regular source grid');
    return spacing;
  };
  step(latitudes); step(longitudes);
  const lookup = new Map<string, number>();
  for (const sample of samples) {
    if (!Number.isFinite(sample.value)) throw new Error('Display raster cannot use non-finite source values');
    const key = `${sample.latitude}|${sample.longitude}`;
    if (lookup.has(key)) throw new Error('Display raster cannot use duplicate source cells');
    lookup.set(key, sample.value);
  }
  const values = latitudes.map(latitude => longitudes.map(longitude => {
    const value = lookup.get(`${latitude}|${longitude}`);
    if (value === undefined) throw new Error('Display raster cannot fill missing source cells');
    return value;
  }));
  const flattened = samples.map(sample => sample.value);
  return { latitudes, longitudes, values, south: latitudes[0], north: latitudes.at(-1)!,
    west: longitudes[0], east: longitudes.at(-1)!,
    min: Math.min(...flattened), max: Math.max(...flattened) };
}

/** Source-cell picking/overlays stop at the displayed model-domain boundary. */
export function cellBounds(grid: RegularGrid, latitude: number, longitude: number): [[number, number], [number, number]] {
  const halfLatitude = (grid.latitudes[1] - grid.latitudes[0]) / 2;
  const halfLongitude = (grid.longitudes[1] - grid.longitudes[0]) / 2;
  return [[Math.max(grid.south, latitude - halfLatitude), Math.max(grid.west, longitude - halfLongitude)],
    [Math.min(grid.north, latitude + halfLatitude), Math.min(grid.east, longitude + halfLongitude)]];
}

/** Bilinear sampling for display pixels only. Original API cells remain authoritative. */
export function sampleDisplayValue(grid: RegularGrid, latitude: number, longitude: number): number {
  const rows = grid.latitudes.length, columns = grid.longitudes.length;
  const y = Math.max(0, Math.min(rows - 1, (latitude - grid.latitudes[0]) / (grid.latitudes[1] - grid.latitudes[0])));
  const x = Math.max(0, Math.min(columns - 1, (longitude - grid.longitudes[0]) / (grid.longitudes[1] - grid.longitudes[0])));
  const y0 = Math.floor(y), y1 = Math.min(rows - 1, y0 + 1), x0 = Math.floor(x), x1 = Math.min(columns - 1, x0 + 1);
  const fy = y - y0, fx = x - x0;
  return (1 - fy) * ((1 - fx) * grid.values[y0][x0] + fx * grid.values[y0][x1]) +
    fy * ((1 - fx) * grid.values[y1][x0] + fx * grid.values[y1][x1]);
}

export function divergingRgb(value: number, maximumMagnitude: number): [number, number, number] {
  const neutral = [246, 247, 241], negative = [54, 137, 248], positive = [245, 79, 74];
  const fraction = maximumMagnitude <= 0 ? 0 : Math.min(1, Math.abs(value) / maximumMagnitude);
  const target = value < 0 ? negative : positive;
  return neutral.map((channel, index) => Math.round(channel + (target[index] - channel) * fraction)) as [number, number, number];
}

/** One seam-free PNG over the exact grid footprint; recomputed only when source/layer changes. */
export function renderDisplayRaster(grid: RegularGrid, palette: RasterPalette, size = 512,
  colorRange?: [number, number], geometry?: StateGeometry): string {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas rendering is unavailable');
  const image = context.createImageData(size, size);
  const low = colorRange?.[0] ?? grid.min;
  const high = colorRange?.[1] ?? grid.max;
  const maximumMagnitude = Math.max(Math.abs(grid.min), Math.abs(grid.max));
  for (let row = 0; row < size; row++) {
    const latitude = geometry ? inverseMercatorY(mercatorY(grid.north) - (row + .5) *
      (mercatorY(grid.north) - mercatorY(grid.south)) / size) :
      grid.north - (row + .5) * (grid.north - grid.south) / size;
    for (let column = 0; column < size; column++) {
      const longitude = grid.west + (column + .5) * (grid.east - grid.west) / size;
      const value = sampleDisplayValue(grid, latitude, longitude);
      const rgb = palette === 'difference' ? divergingRgb(value, maximumMagnitude) :
        palette === 'confidence' ? heatRgb(100 - value, 0, 100) : heatRgb(value, low, high);
      const index = 4 * (row * size + column);
      image.data[index] = rgb[0]; image.data[index + 1] = rgb[1]; image.data[index + 2] = rgb[2]; image.data[index + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  if (geometry) maskRasterToState(canvas, grid, geometry);
  return canvas.toDataURL('image/png');
}

/** Existing hotspot cell fills/outlines, rasterized and clipped for display only. */
export function renderStateHotspots(grid: RegularGrid, hotspots: Hotspot[], geometry: StateGeometry,
  selectedHotspot?: string | null, size = 512): string {
  const canvas = document.createElement('canvas');
  canvas.width = size; canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas rendering is unavailable');
  for (const hotspot of hotspots) {
    context.fillStyle = '#e9554c';
    context.globalAlpha = selectedHotspot === hotspot.hotspot_id ? .25 : selectedHotspot ? .05 : .13;
    for (const cell of hotspot.member_cells) {
      const [[south, west], [north, east]] = cellBounds(grid, cell.latitude, cell.longitude);
      const [left, top] = projectedPixel(grid, north, west, size);
      const [right, bottom] = projectedPixel(grid, south, east, size);
      context.fillRect(left, top, right - left, bottom - top);
    }
    context.strokeStyle = '#c9504b';
    context.lineWidth = selectedHotspot === hotspot.hotspot_id ? 3 : 1.8;
    context.globalAlpha = selectedHotspot && selectedHotspot !== hotspot.hotspot_id ? .35 : .9;
    for (const [first, second] of hotspotOutline(hotspot, grid.latitudes[1] - grid.latitudes[0],
      grid.longitudes[1] - grid.longitudes[0], grid)) {
      const [x1, y1] = projectedPixel(grid, first[0], first[1], size);
      const [x2, y2] = projectedPixel(grid, second[0], second[1], size);
      context.beginPath(); context.moveTo(x1, y1); context.lineTo(x2, y2); context.stroke();
    }
  }
  context.globalAlpha = 1;
  maskRasterToState(canvas, grid, geometry);
  return canvas.toDataURL('image/png');
}

/** Preserve the selected source-cell outline, clipped at the state boundary. */
export function renderSelectedCellOutline(grid: RegularGrid, latitude: number, longitude: number,
  geometry: StateGeometry, size = 512): string {
  const canvas = document.createElement('canvas');
  canvas.width = size; canvas.height = size;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas rendering is unavailable');
  const [[south, west], [north, east]] = cellBounds(grid, latitude, longitude);
  const [left, top] = projectedPixel(grid, north, west, size);
  const [right, bottom] = projectedPixel(grid, south, east, size);
  context.strokeStyle = '#223a2c'; context.lineWidth = 2.5;
  context.strokeRect(left, top, right - left, bottom - top);
  maskRasterToState(canvas, grid, geometry);
  return canvas.toDataURL('image/png');
}
