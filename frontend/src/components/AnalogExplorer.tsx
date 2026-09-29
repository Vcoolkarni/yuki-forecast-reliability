import { History } from 'lucide-react';
import { State } from './State';
import { useRemote } from '../hooks/useRemote';
import { api } from '../services/api';
import { coordinates, dateUTC } from '../services/format';

export function AnalogExplorer({ initialization, lead, latitude, longitude }: { initialization: string; lead: number; latitude: number; longitude: number }) {
  const analogs = useRemote(signal => api.analogs(initialization, lead, latitude, longitude, 5, signal), [initialization, lead, latitude, longitude]);
  return <section className="card analog-section"><div className="card-heading"><div><h3><History size={18} /> Similar Historical Situations</h3><span>Forecast-feature similarity · Day {lead} · {coordinates(latitude, longitude)}</span></div></div>
    <State loading={analogs.loading} error={analogs.error} empty={!analogs.data}>{analogs.data && <>
      {analogs.data.number_of_analogs === 0 ? <p className="muted">No eligible historical analogs are available for this lead day.</p> : <>
        <div className="analog-summary"><div><small>Analog events</small><strong>{analogs.data.number_of_analogs}</strong></div><div><small>Historical bust labels</small><strong>{analogs.data.percentage_busted?.toFixed(0)}%</strong></div><div><small>Mean historical absolute error</small><strong>{analogs.data.mean_historical_absolute_error?.toFixed(1)} mm</strong></div></div>
        <p className="muted">{analogs.data.analogs.filter(item => item.is_bust).length} of the {analogs.data.number_of_analogs} most similar historical situations were classified as forecast busts. This is historical verification, not a probability forecast.</p>
        <div className="analog-list">{analogs.data.analogs.map(item => <div key={`${item.initialization_time},${item.latitude},${item.longitude}`}>
          <div><strong>{dateUTC(item.initialization_time)}</strong><small>{coordinates(item.latitude, item.longitude)} · Day {item.lead_day}</small></div>
          <div><small>Similarity</small><strong>{(item.similarity_score * 100).toFixed(0)}%</strong></div>
          <div><small>Forecast / ERA5 reanalysis</small><strong>{item.forecast_precipitation.toFixed(1)} / {item.reference_precipitation.toFixed(1)} mm</strong></div>
          <div><small>Absolute error</small><strong>{item.absolute_error.toFixed(1)} mm</strong></div>
          <span className={`badge ${item.is_bust ? 'risk' : 'neutral'}`}>{item.is_bust ? 'Historical bust' : 'No historical bust'}</span>
        </div>)}</div></>}
      <p className="muted provenance">{analogs.data.provenance}</p></>}</State></section>;
}
