import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AnalogExplorer } from './AnalogExplorer';

afterEach(() => vi.unstubAllGlobals());
describe('historical analog rendering', () => {
  it('shows real-response historical outcomes and clearly labels ERA5 reanalysis', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      initialization_time: '2026-09-12T00:00:00Z', latitude: 22, longitude: 78, lead_day: 5,
      number_of_analogs: 1, percentage_busted: 100, mean_historical_absolute_error: 24,
      provenance: 'Historical GFS forecasts matched with ERA5 reanalysis; fixed 20 mm definition.',
      analogs: [{ initialization_time: '2026-07-04T00:00:00Z', lead_day: 5, latitude: 22,
        longitude: 78, similarity_score: .8, distance: .25, forecast_precipitation: 30,
        reference_precipitation: 6, absolute_error: 24, is_bust: true }]
    }) }));
    render(<AnalogExplorer initialization="2026-09-12T00:00:00Z" lead={5} latitude={22} longitude={78} />);
    expect(await screen.findByText('Historical bust')).toBeTruthy();
    expect(screen.getByText(/30.0 \/ 6.0 mm/)).toBeTruthy();
    expect(screen.getAllByText(/ERA5 reanalysis/)).toHaveLength(2);
  });
  it('shows an explicit empty state when no analogs qualify', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      initialization_time: '2026-09-12T00:00:00Z', latitude: 22, longitude: 78, lead_day: 5,
      number_of_analogs: 0, percentage_busted: null, mean_historical_absolute_error: null,
      provenance: 'Historical dataset', analogs: []
    }) }));
    render(<AnalogExplorer initialization="2026-09-12T00:00:00Z" lead={5} latitude={22} longitude={78} />);
    expect(await screen.findByText(/No eligible historical analogs/)).toBeTruthy();
  });
});
