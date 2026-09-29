import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Explain } from './Explain';
import { SelectionProvider, useSelection } from '../hooks/SelectionContext';

vi.mock('../components/ForecastMap', () => ({ ForecastMap: ({ selectedCell }: {
  selectedCell?: { latitude: number; longitude: number }
}) => <div>Context map: {selectedCell?.latitude}, {selectedCell?.longitude}</div> }));
vi.mock('../components/Charts', () => ({ CellRiskChart: () => <div>Risk timeline</div> }));
afterEach(() => vi.unstubAllGlobals());

function WithSelection() {
  const selection = useSelection();
  return <><button onClick={() => selection.selectLocation({ latitude: 22.5, longitude: 78 })}>Select from another screen</button>
    <Explain initialization="2026-09-12" lead={5} /></>;
}
describe('model explanation', () => {
  it('follows the shared selected grid cell and shows real-response contribution signs and historical analogs', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/day/5')) return { ok: true, json: async () => ({ records: [22.5, 22.75].flatMap(latitude => [78, 78.25].map(longitude => ({ latitude, longitude }))) }) };
      if (url.includes('/cell/analogs')) return { ok: true, json: async () => ({
        number_of_analogs: 1, percentage_busted: 100, mean_historical_absolute_error: 24,
        provenance: 'Historical GFS matched with ERA5 reanalysis; fixed 20 mm label.',
        analogs: [{ initialization_time: '2026-07-01T00:00:00Z', latitude: 22.5, longitude: 78,
          lead_day: 5, similarity_score: .8, forecast_precipitation: 30,
          reference_precipitation: 6, absolute_error: 24, is_bust: true }]
      }) };
      if (url.includes('/cell?')) return { ok: true, json: async () => ({
        latitude: 22.5, longitude: 78, lead_day: 5, bust_probability: .64, confidence_score: 36,
        is_bust_predicted: true, explanation_summary: 'Factors influencing the model prediction: precipitation and wind.',
        explanations: [{ feature: 'forecast_precipitation', feature_value: 30, contribution: .4,
          direction: 'increases_model_bust_score' }, { feature: 'forecast_wind_speed_10m',
          feature_value: 5, contribution: -.2, direction: 'decreases_model_bust_score' }]
      }) };
      throw new Error(`Unexpected route ${url}`);
    }));
    render(<SelectionProvider><WithSelection/></SelectionProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Select from another screen' }));
    expect(await screen.findByText('Context map: 22.5, 78')).toBeTruthy();
    expect(await screen.findByText('64.0%')).toBeTruthy();
    expect(screen.getByText(/Raw model log-odds before calibration/)).toBeTruthy();
    expect(screen.getByText(/do not prove meteorological causality/)).toBeTruthy();
    expect(await screen.findByText(/1 of the 1 most similar historical situations/)).toBeTruthy();
  });
});
