import { useMemo } from 'react';
import { ForecastMap } from '../components/ForecastMap';
import { CellRiskChart } from '../components/Charts';
import { State } from '../components/State';
import { useRemote } from '../hooks/useRemote';
import { api } from '../services/api';
import { confidencePercent, coordinates, percent, splitContributions } from '../services/format';
import { AnalogExplorer } from '../components/AnalogExplorer';
import { useSelection } from '../hooks/SelectionContext';
import { useSelectedStateGeometry } from '../maps/useSelectedStateGeometry';
import { stateCells } from '../maps/stateClip';

export function Explain({ initialization, lead, selectedState: selectedStateProp }: { initialization: string; lead: number; selectedState?: string }) {
  const selectedState = selectedStateProp || 'Madhya Pradesh';
  const geometry = useSelectedStateGeometry(selectedStateProp);
  const selection = useSelection();
  const day = useRemote(signal => api.day(initialization, lead, signal), [initialization, lead]);
  const eligible = useMemo(() => selectedStateProp ? geometry ? stateCells(day.data?.records || [], geometry) : [] :
    day.data?.records || [], [selectedStateProp, geometry, day.data]);
  const center = eligible[Math.floor((eligible.length || 1) / 2)];
  const chosen = eligible.find(item => item.latitude === selection.location?.latitude && item.longitude === selection.location.longitude);
  const point = chosen ? selection.location : center ? { latitude: center.latitude, longitude: center.longitude } : null;
  const cell = useRemote(signal => point ? api.cell(initialization, lead, point.latitude, point.longitude, signal) : Promise.reject(new Error('Select a grid cell.')),
    [initialization, lead, point?.latitude, point?.longitude]);
  const timeline = useRemote(async signal => {
    if (!point) return [];
    return Promise.all(Array.from({ length: 10 }, (_, i) => api.cell(initialization, i + 1, point.latitude, point.longitude, signal)));
  }, [initialization, point?.latitude, point?.longitude]);
  const { positive, negative } = splitContributions(cell.data?.explanations || []);
  return <div className="page"><div className="page-heading"><div><div className="eyebrow">MODEL EXPLANATION · {selectedState.toUpperCase()}</div><h1>Why This <em>Forecast?</em></h1><p>See what influenced the model prediction for a selected forecast grid cell.</p></div></div>
    <div className="explain-select"><label>Grid cell <select aria-label="Grid cell" value={point ? `${point.latitude},${point.longitude}` : ''} onChange={event => { const [latitude, longitude] = event.target.value.split(',').map(Number); selection.selectLocation({ latitude, longitude }); }}>
      {eligible.map(item => <option key={`${item.latitude},${item.longitude}`} value={`${item.latitude},${item.longitude}`}>{coordinates(item.latitude, item.longitude)}</option>)}
    </select></label><span>Day {lead} · {point && coordinates(point.latitude, point.longitude)}</span></div>
    <div className="explain-grid"><section className="card"><h3>Model Prediction <span>(Day {lead})</span></h3><State loading={day.loading || cell.loading} error={day.error || cell.error} empty={!cell.data}>
      {cell.data && <><div className="stat-grid"><div><small>Bust probability</small><strong>{percent(cell.data.bust_probability, 1)}</strong></div><div><small>Model-derived confidence</small><strong>{confidencePercent(cell.data.confidence_score)}</strong></div></div>
        <p className="muted">{cell.data.is_bust_predicted ? 'Predicted bust' : 'Below predicted-bust threshold'} · {coordinates(cell.data.latitude, cell.data.longitude)}</p>
        <p className="muted">Expected absolute error: {cell.data.expected_absolute_error_mm?.toFixed(1) ?? '—'} mm · GEFS final six-hour spread: {cell.data.gefs_end_window_spread_6h_mm?.toFixed(1) ?? '—'} mm (not daily spread).</p></>}</State>
      <State loading={day.loading || timeline.loading} error={day.error || timeline.error} empty={!timeline.data?.length}>{timeline.data && <CellRiskChart values={timeline.data} active={lead} />}</State></section>
      <section className="card"><h3>Top Contributing Factors <span>(TreeSHAP)</span></h3><State loading={day.loading || cell.loading} error={day.error || cell.error} empty={!cell.data?.explanations.length}>
        <div className="contribution-list">{cell.data?.explanations.map(item => <div key={item.feature}><span>{item.feature.replaceAll('_', ' ')}</span><div className="contribution-track"><i className={item.contribution >= 0 ? 'positive' : 'negative'} style={{ width: `${Math.max(4, 100 * Math.abs(item.contribution) / Math.max(...cell.data!.explanations.map(entry => Math.abs(entry.contribution))))}%` }}/></div><strong>{item.contribution >= 0 ? '+' : ''}{item.contribution.toFixed(3)}</strong></div>)}</div>
        <p className="muted">Raw model log-odds before calibration; these are not probability changes.</p></State></section>
      <section className="card"><h3>Feature Details</h3><State loading={day.loading || cell.loading} error={day.error || cell.error} empty={!cell.data}>
        <div className="detail-grid">{cell.data?.explanations.map(item => <div key={item.feature}><strong>{item.feature.replaceAll('_', ' ')}</strong><span>Forecast value: {item.feature_value.toFixed(3)} · {item.direction.replaceAll('_', ' ')}</span></div>)}</div></State></section></div>
    <div className="bottom-grid two"><section className="card"><h3>Location Context</h3><State loading={day.loading} error={day.error} empty={!day.data?.records.length}><ForecastMap cells={day.data?.records || []} selectedState={selectedStateProp} selectedCell={point} onCell={selection.selectLocation} focusRequest={selection.focusRequest} /></State></section>
      <section className="card"><h3>Model Explanation</h3><State loading={day.loading || cell.loading} error={day.error || cell.error} empty={!cell.data}>
        <p>{cell.data?.explanation_summary}</p><div className="explain-axes"><div><strong>Increases model score</strong>{positive.length ? positive.map(item => <span key={item.feature}>{item.feature.replaceAll('_', ' ')} ({item.contribution.toFixed(3)})</span>) : <span>None in the returned top contributions.</span>}</div>
          <div><strong>Decreases model score</strong>{negative.length ? negative.map(item => <span key={item.feature}>{item.feature.replaceAll('_', ' ')} ({item.contribution.toFixed(3)})</span>) : <span>None in the returned top contributions.</span>}</div></div>
        <p className="muted">These factors influence the model's prediction. They do not prove meteorological causality.</p></State></section></div>
    {point && <AnalogExplorer initialization={initialization} lead={lead} latitude={point.latitude} longitude={point.longitude} />}
  </div>;
}
