import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Overview } from './Overview';
import { useRemote } from '../hooks/useRemote';
import { SelectionProvider, useSelection } from '../hooks/SelectionContext';
import type { GridCell, Health } from '../types/api';

vi.mock('../hooks/useRemote', () => ({ useRemote: vi.fn() }));
vi.mock('../components/ForecastMap', () => ({ ForecastMap: ({ selectedCell, focusRequest }: {
  selectedCell?: { latitude: number; longitude: number }; focusRequest?: number
}) => <div>Map selection: {selectedCell?.latitude ?? 'none'}, {selectedCell?.longitude ?? 'none'}; focus {focusRequest}</div> }));
vi.mock('../components/Charts', () => ({ ConfidenceChart: () => <div>Confidence chart</div> }));
vi.mock('../maps/useSelectedStateGeometry', () => ({ useSelectedStateGeometry: () => ({ type: 'Polygon',
  coordinates: [[[77, 22], [79, 22], [79, 23], [77, 23], [77, 22]]] }) }));

const cell: GridCell = { initialization_time: '2026-09-12T00:00:00Z', valid_time: '2026-09-17T00:00:00Z',
  lead_day: 5, latitude: 22.5, longitude: 78, forecast_precipitation: 10,
  forecast_temperature_2m: 300, forecast_relative_humidity_2m: 70,
  forecast_mean_sea_level_pressure: 100000, forecast_u_wind_10m: 3, forecast_v_wind_10m: 4,
  forecast_wind_speed_10m: 5, precipitation_gradient_mm_per_degree: 2,
  bust_probability: .64, confidence_score: 36, confidence_category: 'Low', is_bust_predicted: true,
  decision_threshold: .3, explanations: [], explanation_summary: 'Model factors.', explanation_base_value: -1 };
const summary = { lead_day: 5, number_of_predictions: 289, mean_bust_probability: .3,
  maximum_bust_probability: .99, mean_confidence: 70, percentage_predicted_bust: 10,
  highest_risk_location: { latitude: 22.5, longitude: 78, lead_day: 5, bust_probability: .64 }, hotspot_count: 1 };
const health: Health = { api_ready: true, model_ready: true, forecast_ready: true, status: 'ready', model_id: 'test',
  decision_threshold: .3, features: [], available_initializations: ['2026-09-11T00:00:00Z', '2026-09-12T00:00:00Z'],
  cached_initializations: 0, grid: null };
const ready = (data: unknown) => ({ data, loading: false, error: null }) as never;

function Destination() {
  const selection = useSelection();
  return <div>Explain selected: {selection.location?.latitude}, {selection.location?.longitude}</div>;
}
beforeEach(() => {
  vi.mocked(useRemote).mockReset();
  const stateDay = { state: 'Madhya Pradesh', lead_day: 5, grid_cell_count: 1,
    mean_forecast_confidence: 36, mean_bust_probability: .64, predicted_bust_cell_percentage: 100,
    mean_expected_absolute_error_mm: 8, mean_gefs_end_window_spread_6h_mm: 3,
    highest_risk_cell: cell, hotspot_count: 1 };
  const responses = [ready({ lead_day_summaries: [summary] }), ready({ records: [cell] }), ready(cell),
    ready({ hotspots: [] }), ready(stateDay), ready({ days: [stateDay], most_uncertain_lead_day: 5, grid_cell_count: 1 }),
    ready({ text: 'Real brief', caveat: 'Model-derived.' })];
  let call = 0;
  vi.mocked(useRemote).mockImplementation(() => responses[call++ % responses.length]);
});
describe('highest-risk demo flow', () => {
  it('focuses the real highest-risk cell and navigates to its explanation', () => {
    render(<MemoryRouter><SelectionProvider><Routes><Route path="/" element={<Overview initialization="2026-09-12T00:00:00Z" lead={5} health={health} />} />
      <Route path="/explain" element={<Destination/>} /></Routes></SelectionProvider></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Focus highest risk' }));
    expect(screen.getByText(/Map selection: 22.5, 78; focus 1/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Explain this risk' }));
    expect(screen.getByText('Explain selected: 22.5, 78')).toBeTruthy();
  });
  it('uses only selected-state grid centers for overview maximum and weather metrics', () => {
    const outside = { ...cell, latitude: 30, forecast_temperature_2m: 400,
      forecast_precipitation: 100, bust_probability: .99 };
    const stateDay = { state: 'Madhya Pradesh', lead_day: 5, grid_cell_count: 1,
      mean_forecast_confidence: 36, mean_bust_probability: .64, predicted_bust_cell_percentage: 100,
      mean_expected_absolute_error_mm: 8, mean_gefs_end_window_spread_6h_mm: 3,
      highest_risk_cell: cell, hotspot_count: 1 };
    const responses = [ready({ lead_day_summaries: [summary] }), ready({ records: [cell, outside] }),
      ready(outside), ready({ hotspots: [] }), ready(stateDay),
      ready({ days: [stateDay], most_uncertain_lead_day: 5, grid_cell_count: 1 }),
      ready({ text: 'Real brief', caveat: 'Model-derived.' })];
    let call = 0;
    vi.mocked(useRemote).mockImplementation(() => responses[call++ % responses.length]);
    render(<MemoryRouter><SelectionProvider><Overview initialization="2026-09-12T00:00:00Z"
      lead={5} health={health} selectedState="Madhya Pradesh" /></SelectionProvider></MemoryRouter>);
    expect(screen.getAllByText('64%').length).toBeGreaterThan(0);
    expect(screen.queryByText('99%')).toBeNull();
    expect(screen.getByText('26.9°C')).toBeTruthy();
    expect(screen.getByText('10.0 mm')).toBeTruthy();
  });
  it('keeps loading when new-lead hotspots arrive before the matching grid', () => {
    const stateDay = { state: 'Madhya Pradesh', lead_day: 7, grid_cell_count: 1,
      mean_forecast_confidence: 36, mean_bust_probability: .64, predicted_bust_cell_percentage: 100,
      mean_expected_absolute_error_mm: 8, mean_gefs_end_window_spread_6h_mm: 3,
      highest_risk_cell: cell, hotspot_count: 1 };
    const earlyHotspots = { lead_day: 7, hotspots: [{ hotspot_id: 'risk-7', lead_day: 7,
      member_cells: [{ latitude: 22.5, longitude: 78 }], number_of_cells: 1,
      centroid_latitude: 22.5, centroid_longitude: 78, mean_bust_probability: .64,
      max_bust_probability: .64, mean_confidence: 36,
      bounding_box: { south: 22.5, north: 22.5, west: 78, east: 78 } }] };
    const responses = [ready({ lead_day_summaries: [summary] }),
      { data: null, loading: true, error: null } as never, ready(cell), ready(earlyHotspots),
      ready(stateDay), ready({ days: [stateDay], most_uncertain_lead_day: 7, grid_cell_count: 1 }),
      ready({ text: 'Real brief', caveat: 'Model-derived.' })];
    let call = 0;
    vi.mocked(useRemote).mockImplementation(() => responses[call++ % responses.length]);
    render(<MemoryRouter><SelectionProvider><Overview initialization="2026-09-12T00:00:00Z"
      lead={7} health={health} selectedState="Madhya Pradesh" /></SelectionProvider></MemoryRouter>);
    expect(screen.getAllByRole('status').length).toBeGreaterThan(0);
  });
});
