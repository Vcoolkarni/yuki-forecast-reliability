import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Analysis } from './Analysis';
import { SelectionProvider } from '../hooks/SelectionContext';

vi.mock('../components/ForecastMap', () => ({ ForecastMap: ({ cells, layer }: {
  cells: { initialization_time: string; lead_day: number; forecast_precipitation: number }[]; layer: string
}) => <div>Map layer: {layer}; run: {cells[0]?.initialization_time}; Day {cells[0]?.lead_day}; rain {cells[0]?.forecast_precipitation}</div> }));
vi.mock('../components/Charts', () => ({ VariableChart: ({ values }: { values: { lead_day: number }[] }) => <div>Trend points: {values.length}</div> }));
afterEach(() => vi.unstubAllGlobals());

describe('forecast analysis layer and run switching', () => {
  it('updates layer, initialization, and Day 1/5/10 from API responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/variables/trend')) return { ok: true, json: async () => ({ days: Array.from({ length: 10 }, (_, i) => ({ lead_day: i + 1, value: 10 })) }) };
      const lead = Number(url.match(/\/day\/(\d+)/)?.[1]);
      const initialization = decodeURIComponent(url).includes('2026-09-11') ? '2026-09-11' : '2026-09-12';
      const records = [20, 20.25].flatMap(latitude => [76, 76.25].map(longitude => ({
        initialization_time: initialization, latitude, longitude, lead_day: lead,
        forecast_precipitation: lead, forecast_temperature_2m: 300,
        forecast_relative_humidity_2m: 70, forecast_mean_sea_level_pressure: 100000,
        forecast_wind_speed_10m: 5, precipitation_gradient_mm_per_degree: 2
      })));
      return { ok: true, json: async () => ({ records }) };
    }));
    const view = render(<SelectionProvider><Analysis initialization="2026-09-11" lead={1} /></SelectionProvider>);
    expect(await screen.findByText(/Map layer: forecast_temperature_2m; run: 2026-09-11; Day 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Precipitation' }));
    expect(await screen.findByText(/Map layer: forecast_precipitation; run: 2026-09-11; Day 1/)).toBeTruthy();
    view.rerender(<SelectionProvider><Analysis initialization="2026-09-11" lead={5} /></SelectionProvider>);
    expect(await screen.findByText(/Map layer: forecast_precipitation; run: 2026-09-11; Day 5; rain 5/)).toBeTruthy();
    view.rerender(<SelectionProvider><Analysis initialization="2026-09-12" lead={10} /></SelectionProvider>);
    expect(await screen.findByText(/Map layer: forecast_precipitation; run: 2026-09-12; Day 10; rain 10/)).toBeTruthy();
    expect(screen.getByText(/Trend points: 10/)).toBeTruthy();
  });
});
