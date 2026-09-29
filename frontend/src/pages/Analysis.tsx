import { useMemo, useState } from 'react';
import { ForecastMap } from '../components/ForecastMap';
import { VariableChart } from '../components/Charts';
import { State } from '../components/State';
import { useRemote } from '../hooks/useRemote';
import { api } from '../services/api';
import { coordinates, kelvinToCelsius, layerValue, layers, metersPerSecondToKmh, type WeatherLayer } from '../services/format';
import type { GridCell } from '../types/api';
import { useSelection } from '../hooks/SelectionContext';
import { useSelectedStateGeometry } from '../maps/useSelectedStateGeometry';
import { stateCells } from '../maps/stateClip';

const available = layers.filter(item => !['bust_probability', 'confidence_score'].includes(item.key));
export function Analysis({ initialization, lead, selectedState: selectedStateProp }: { initialization: string; lead: number; selectedState?: string }) {
  const selectedState = selectedStateProp || 'Madhya Pradesh';
  const geometry = useSelectedStateGeometry(selectedStateProp);
  const [layer, setLayer] = useState<WeatherLayer>('forecast_temperature_2m');
  const selection = useSelection();
  const day = useRemote(signal => api.day(initialization, lead, signal), [initialization, lead]);
  const stateDay = useRemote(signal => api.stateDay(initialization, selectedState, lead, signal), [initialization, selectedState, lead]);
  const cells = useMemo(() => selectedStateProp ? geometry ? stateCells(day.data?.records || [], geometry) : [] :
    day.data?.records || [], [selectedStateProp, geometry, day.data]);
  const selectedCell = cells.find(cell => cell.latitude === selection.location?.latitude && cell.longitude === selection.location.longitude) || cells[Math.floor((cells.length || 1) / 2)];
  const values = cells.map(cell => layerValue(cell, layer));
  const mean = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
  const info = layers.find(item => item.key === layer)!;
  const trend = useRemote(async signal => {
    const result = await api.variableTrend(initialization, layer, signal);
    return result.days.map(item => ({ ...item, value: layer === 'forecast_temperature_2m' ? kelvinToCelsius(item.value)
      : layer === 'forecast_wind_speed_10m' ? metersPerSecondToKmh(item.value)
      : layer === 'forecast_mean_sea_level_pressure' ? item.value / 100 : item.value }));
  }, [initialization, layer]);
  const ranked = useMemo(() => [...cells].sort((a, b) => layerValue(b, layer) - layerValue(a, layer)).slice(0, 5), [cells, layer]);
  return <div className="page"><div className="page-heading"><div><div className="eyebrow">{selectedState.toUpperCase()}</div><h1>Forecast <em>Analysis</em></h1><p>Explore the forecast fields that are available to the model.</p></div></div>
    <div className="analysis-grid"><section className="card map-card large"><div className="card-heading"><h3>Weather Layers</h3><span>Day {lead} · GFS forecast</span></div>
      <div className="layer-tabs" role="group" aria-label="Weather layer">{available.map(item => <button key={item.key} className={layer === item.key ? 'selected' : ''} onClick={() => setLayer(item.key)}>{item.label}</button>)}</div>
      <State loading={day.loading} error={day.error} empty={!day.data?.records.length}><ForecastMap cells={day.data?.records || []} layer={layer} selectedState={selectedStateProp} selectedCell={selectedCell}
        onCell={selection.selectLocation} focusRequest={selection.focusRequest} /></State></section>
      <div className="side-stack"><section className="card"><h3>Regional Forecast <span>(Day {lead})</span></h3><State loading={day.loading} error={day.error} empty={!cells.length}>
        <div className="stat-grid"><div><small>Mean {info.label.toLowerCase()}</small><strong>{mean.toFixed(1)} {info.unit}</strong></div><div><small>Highest grid value</small><strong>{Math.max(...values).toFixed(1)} {info.unit}</strong></div></div>
        <p className="muted">{selectedState} grid-center forecast values at the selected lead, not observed conditions.</p></State>
        <State loading={stateDay.loading} error={stateDay.error}>{stateDay.data?.mean_expected_absolute_error_mm !== undefined && <p className="muted">{selectedState}: {stateDay.data.grid_cell_count} grid centers · expected absolute error {stateDay.data.mean_expected_absolute_error_mm.toFixed(1)} mm · GEFS final six-hour spread {stateDay.data.mean_gefs_end_window_spread_6h_mm.toFixed(1)} mm (not daily spread).</p>}</State></section>
        <section className="card"><h3>Forecast Trend <span>(Model-domain mean · Day 1–10)</span></h3><State loading={trend.loading} error={trend.error}>{trend.data && <VariableChart values={trend.data} unit={info.unit} />}</State></section></div></div>
    <div className="bottom-grid two"><section className="card"><h3>Selected Grid Cell</h3><State loading={day.loading} error={day.error} empty={!selectedCell}>
      {selectedCell && <div className="detail-grid"><strong>{coordinates(selectedCell.latitude, selectedCell.longitude)}</strong><span>{info.label}: {layerValue(selectedCell, layer).toFixed(1)} {info.unit}</span><span>Precipitation: {selectedCell.forecast_precipitation.toFixed(1)} mm</span><span>Relative humidity: {selectedCell.forecast_relative_humidity_2m.toFixed(0)}%</span><span>Expected absolute error: {selectedCell.expected_absolute_error_mm?.toFixed(1) ?? '—'} mm</span><span>GEFS final six-hour spread: {selectedCell.gefs_end_window_spread_6h_mm?.toFixed(1) ?? '—'} mm</span></div>}</State></section>
      <section className="card"><h3>Grid-Cell Comparison <span>(Day {lead})</span></h3><State loading={day.loading} error={day.error} empty={!ranked.length}>
        <div className="rank-list">{ranked.map((cell: GridCell) => <button key={`${cell.latitude}-${cell.longitude}`} onClick={() => selection.focusLocation(cell)}><span>{coordinates(cell.latitude, cell.longitude)}</span><strong>{layerValue(cell, layer).toFixed(1)} {info.unit}</strong></button>)}</div></State></section></div>
  </div>;
}
