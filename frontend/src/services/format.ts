import type { Contribution, GridCell } from '../types/api';

export const percent = (value: number, digits = 0) => `${(value * 100).toFixed(digits)}%`;
export const confidencePercent = (value: number) => `${value.toFixed(0)}%`;
export const coordinates = (latitude: number, longitude: number) => `${latitude.toFixed(2)}°N, ${longitude.toFixed(2)}°E`;
export const dateUTC = (value: string) => new Date(value).toLocaleDateString('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' });
export const kelvinToCelsius = (kelvin: number) => kelvin - 273.15;
export const metersPerSecondToKmh = (speed: number) => speed * 3.6;
export const percentagePointDelta = (current: number, previous: number) => 100 * (current - previous);
export const splitContributions = (items: Contribution[]) => ({
  positive: items.filter(item => item.contribution > 0),
  negative: items.filter(item => item.contribution < 0)
});
export type WeatherLayer = 'bust_probability' | 'confidence_score' | 'forecast_precipitation' |
  'forecast_temperature_2m' | 'forecast_relative_humidity_2m' | 'forecast_mean_sea_level_pressure' |
  'forecast_wind_speed_10m' | 'precipitation_gradient_mm_per_degree' |
  'expected_absolute_error_mm' | 'gefs_end_window_spread_6h_mm';
export const layers: { key: WeatherLayer; label: string; unit: string; value: (cell: GridCell) => number }[] = [
  { key: 'bust_probability', label: 'Bust probability', unit: '%', value: cell => cell.bust_probability * 100 },
  { key: 'confidence_score', label: 'Confidence', unit: '%', value: cell => cell.confidence_score },
  { key: 'forecast_temperature_2m', label: 'Temperature', unit: '°C', value: cell => kelvinToCelsius(cell.forecast_temperature_2m) },
  { key: 'forecast_precipitation', label: 'Precipitation', unit: 'mm', value: cell => cell.forecast_precipitation },
  { key: 'forecast_relative_humidity_2m', label: 'Humidity', unit: '%', value: cell => cell.forecast_relative_humidity_2m },
  { key: 'forecast_wind_speed_10m', label: 'Wind speed', unit: 'km/h', value: cell => metersPerSecondToKmh(cell.forecast_wind_speed_10m) },
  { key: 'forecast_mean_sea_level_pressure', label: 'Mean sea-level pressure', unit: 'hPa', value: cell => cell.forecast_mean_sea_level_pressure / 100 },
  { key: 'precipitation_gradient_mm_per_degree', label: 'Precipitation gradient', unit: 'mm/degree', value: cell => cell.precipitation_gradient_mm_per_degree },
  { key: 'expected_absolute_error_mm', label: 'Expected absolute error', unit: 'mm', value: cell => cell.expected_absolute_error_mm ?? 0 },
  { key: 'gefs_end_window_spread_6h_mm', label: 'GEFS 6h spread', unit: 'mm', value: cell => cell.gefs_end_window_spread_6h_mm ?? 0 }
];
export function layerValue(cell: GridCell, key: WeatherLayer): number {
  return layers.find(layer => layer.key === key)!.value(cell);
}

// Data values determine positions along the reference's blue→cyan→yellow→red legend.
const stops = [ [54, 137, 248], [67, 205, 218], [214, 236, 137], [255, 183, 76], [245, 79, 74] ];
export function heatRgb(value: number, min: number, max: number): [number, number, number] {
  const fraction = max <= min ? 0.5 : Math.max(0, Math.min(1, (value - min) / (max - min)));
  const scaled = fraction * (stops.length - 1), index = Math.min(stops.length - 2, Math.floor(scaled));
  const mix = scaled - index;
  return stops[index].map((part, channel) => Math.round(part + (stops[index + 1][channel] - part) * mix)) as [number, number, number];
}
export function heatColor(value: number, min: number, max: number): string {
  return `rgb(${heatRgb(value, min, max).join(',')})`;
}
