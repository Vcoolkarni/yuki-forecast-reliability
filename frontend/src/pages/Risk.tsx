import { useEffect, useMemo, useState } from 'react';
import { ForecastMap } from '../components/ForecastMap';
import { State } from '../components/State';
import { useRemote } from '../hooks/useRemote';
import { api } from '../services/api';
import { coordinates, percent } from '../services/format';
import { useSelection } from '../hooks/SelectionContext';
import { useSelectedStateGeometry } from '../maps/useSelectedStateGeometry';
import { stateCells, stateHotspots } from '../maps/stateClip';
import type { Health } from '../types/api';

export function Risk({ initialization, lead, selectedState: selectedStateProp, availableInitializations = [], runMetadata }: {
  initialization: string; lead: number; selectedState?: string; availableInitializations?: string[];
  runMetadata?: Health['run_metadata'] }) {
  const selectedState = selectedStateProp || 'Madhya Pradesh';
  const geometry = useSelectedStateGeometry(selectedStateProp);
  const selection = useSelection();
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => setSelected(null), [initialization, lead, selectedState]);
  const day = useRemote(signal => api.day(initialization, lead, signal), [initialization, lead]);
  const hotspots = useRemote(signal => api.hotspots(initialization, lead, signal), [initialization, lead]);
  const stateDay = useRemote(signal => api.stateDay(initialization, selectedState, lead, signal), [initialization, selectedState, lead]);
  const previous = availableInitializations.filter(item => item < initialization && (!runMetadata ||
    runMetadata[item]?.run_kind === runMetadata[initialization]?.run_kind)).at(-1);
  const escalation = useRemote(signal => previous ? api.escalation(initialization, previous, lead, signal) : Promise.resolve(null),
    [initialization, previous, lead]);
  const visibleCells = useMemo(() => selectedStateProp ? geometry ? stateCells(day.data?.records || [], geometry) : [] :
    day.data?.records || [], [selectedStateProp, geometry, day.data]);
  const visibleHotspots = useMemo(() => {
    if (!hotspots.data || !day.data || hotspots.data.lead_day !== day.data.lead_day) return [];
    return selectedStateProp ? geometry ? stateHotspots(hotspots.data.hotspots, day.data.records, geometry) : [] :
      hotspots.data.hotspots;
  }, [selectedStateProp, geometry, hotspots.data, day.data]);
  const ranked = useMemo(() => [...visibleCells].sort((a, b) => b.bust_probability - a.bust_probability).slice(0, 8), [visibleCells]);
  const active = visibleHotspots.find(item => item.hotspot_id === selected);
  return <div className="page"><div className="page-heading"><div><div className="eyebrow">{selectedState.toUpperCase()}</div><h1>Risk &amp; <em>Hotspots</em></h1><p>Find where the model predicts elevated forecast-error risk.</p></div></div>
    <div className="risk-grid"><section className="card map-card large"><div className="card-heading"><div><h3>Elevated-Risk Areas <span>(Day {lead})</span></h3><span>Spatially contiguous cells above the configured risk threshold.</span></div></div>
      <State loading={day.loading || hotspots.loading} error={day.error || hotspots.error} empty={!day.data?.records.length}>
        <ForecastMap cells={day.data?.records || []} hotspots={hotspots.data?.hotspots || []} selectedHotspot={selected} selectedState={selectedStateProp}
          selectedCell={selection.location} onCell={selection.selectLocation} onHotspot={item => setSelected(item.hotspot_id)}
          focusRequest={selection.focusRequest} /></State></section>
      <section className="card"><h3>Highest-Risk Grid Cells <span>({selectedState} · Day {lead})</span></h3><State loading={stateDay.loading} error={stateDay.error}>{stateDay.data?.predicted_bust_cell_percentage !== undefined && <p className="muted">{selectedState}: {stateDay.data.predicted_bust_cell_percentage.toFixed(1)}% predicted bust cells · {stateDay.data.hotspot_count} intersecting hotspots · highest risk {coordinates(stateDay.data.highest_risk_cell.latitude, stateDay.data.highest_risk_cell.longitude)}.</p>}</State><State loading={day.loading} error={day.error} empty={!ranked.length}>
        <div className="rank-list">{ranked.map((cell, index) => <button key={`${cell.latitude}-${cell.longitude}`} onClick={() => selection.focusLocation(cell)}><b className="rank">{index + 1}</b><span>{coordinates(cell.latitude, cell.longitude)}</span><strong>{percent(cell.bust_probability, 1)}</strong><small className={`badge ${cell.is_bust_predicted ? 'risk' : 'neutral'}`}>{cell.is_bust_predicted ? 'Elevated' : 'Below threshold'}</small></button>)}</div></State></section></div>
    <div className="bottom-grid two"><section className="card"><h3>Detected Hotspots <span>(Day {lead})</span></h3><State loading={hotspots.loading} error={hotspots.error}>
      {visibleHotspots.length ? <div className="hotspot-list">{visibleHotspots.map(item => <button key={item.hotspot_id} className={selected === item.hotspot_id ? 'active' : ''} onClick={() => setSelected(selected === item.hotspot_id ? null : item.hotspot_id)}>
        <strong>{item.hotspot_id.replaceAll('-', ' ')}</strong><span>{item.number_of_cells} cells · center {coordinates(item.centroid_latitude, item.centroid_longitude)}</span><b>{percent(item.mean_bust_probability, 1)} mean · {percent(item.max_bust_probability, 1)} max</b></button>)}</div>
        : <p className="muted">No contiguous elevated-risk hotspots for Day {lead}. Individual high-probability cells remain visible in the ranking.</p>}</State></section>
      <section className="card"><h3>Hotspot Details</h3>{active ? <div className="detail-grid"><strong>{active.hotspot_id}</strong><span>Day {active.lead_day} · Centroid: {coordinates(active.centroid_latitude, active.centroid_longitude)}</span><span>Grid cells: {active.number_of_cells}</span><span>Mean bust probability: {percent(active.mean_bust_probability, 1)}</span><span>Maximum bust probability: {percent(active.max_bust_probability, 1)}</span><span>Mean confidence: {active.mean_confidence.toFixed(1)}%</span><span>Bounds: {coordinates(active.bounding_box.south, active.bounding_box.west)} to {coordinates(active.bounding_box.north, active.bounding_box.east)}</span></div>
        : <p className="muted">Select a hotspot to highlight its member cells and inspect its model-derived risk.</p>}</section></div>
    {previous && <div className="subtle-note"><State loading={escalation.loading} error={escalation.error}>{escalation.data && <span>Model-domain run-to-run early warning: {escalation.data.emerging_bust_cells} newly elevated grid cells and {escalation.data.new_hotspot_regions} new hotspot regions versus the previous available run. These totals are not limited to {selectedState}; prediction change, not observed error.</span>}</State></div>}
  </div>;
}
