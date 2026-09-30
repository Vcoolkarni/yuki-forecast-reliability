import { useMemo, useState } from 'react';
import { ArrowRight, Copy, MapPin } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { ConfidenceChart } from '../components/Charts';
import { ForecastMap } from '../components/ForecastMap';
import { DayOverview, WeatherMetrics } from '../components/Metrics';
import { State } from '../components/State';
import { useRemote } from '../hooks/useRemote';
import { api } from '../services/api';
import { coordinates, dateUTC, percent, type WeatherLayer } from '../services/format';
import type { Health } from '../types/api';
import { RunComparison } from '../components/RunComparison';
import { useSelection } from '../hooks/SelectionContext';
import { useSelectedStateGeometry } from '../maps/useSelectedStateGeometry';
import { stateCells, stateHotspots } from '../maps/stateClip';

export function Overview({ initialization, lead, health, selectedState: selectedStateProp }: { initialization: string; lead: number; health: Health; selectedState?: string }) {
  const selectedState = selectedStateProp || 'Madhya Pradesh';
  const geometry = useSelectedStateGeometry(selectedStateProp);
  const navigate = useNavigate();
  const selection = useSelection();
  const [layer, setLayer] = useState<WeatherLayer>('bust_probability');
  const [compareOpen, setCompareOpen] = useState(false);
  const compatibleRuns = health.available_initializations.filter(value => !health.run_metadata ||
    health.run_metadata[value]?.run_kind === health.run_metadata[initialization]?.run_kind);
  const summary = useRemote(signal => api.summary(initialization, signal), [initialization]);
  const day = useRemote(signal => api.day(initialization, lead, signal), [initialization, lead]);
  const highest = useRemote(signal => api.highestRisk(initialization, lead, signal), [initialization, lead]);
  const hotspots = useRemote(signal => api.hotspots(initialization, lead, signal), [initialization, lead]);
  const stateDay = useRemote(signal => api.stateDay(initialization, selectedState, lead, signal), [initialization, selectedState, lead]);
  const stateSummary = useRemote(signal => api.stateSummary(initialization, selectedState, signal), [initialization, selectedState]);
  const stateBrief = useRemote(signal => api.stateBrief(initialization, selectedState, lead, signal), [initialization, selectedState, lead]);
  const visibleCells = useMemo(() => selectedStateProp ? geometry ? stateCells(day.data?.records || [], geometry) : [] :
    day.data?.records || [], [day.data, geometry, selectedStateProp]);
  const visibleHotspots = useMemo(() => {
    // Hotspots and the full grid are independent requests. Never intersect a new
    // lead's hotspot members with an empty/stale grid while the grid is loading.
    if (!hotspots.data || !day.data || hotspots.data.lead_day !== day.data.lead_day) return [];
    return selectedStateProp ? geometry ? stateHotspots(hotspots.data.hotspots, day.data.records, geometry) : [] :
      hotspots.data.hotspots;
  }, [hotspots.data, day.data, geometry, selectedStateProp]);
  const top = useMemo(() => [...visibleCells].sort((a, b) => b.bust_probability - a.bust_probability).slice(0, 5), [visibleCells]);
  const global = summary.data?.lead_day_summaries.find(item => item.lead_day === lead);
  const current = stateDay.data && global ? { ...global, mean_bust_probability: stateDay.data.mean_bust_probability,
    mean_confidence: stateDay.data.mean_forecast_confidence, percentage_predicted_bust: stateDay.data.predicted_bust_cell_percentage,
    maximum_bust_probability: stateDay.data.highest_risk_cell.bust_probability,
    highest_risk_location: stateDay.data.highest_risk_cell, hotspot_count: stateDay.data.hotspot_count,
    number_of_predictions: stateDay.data.grid_cell_count } : selectedStateProp ? null : global;
  const highestCell = stateDay.data?.highest_risk_cell || (selectedStateProp ? null : highest.data);
  const stateTimeline = stateSummary.data?.days.map(item => ({ lead_day: item.lead_day,
    mean_bust_probability: item.mean_bust_probability, maximum_bust_probability: item.highest_risk_cell.bust_probability,
    mean_confidence: item.mean_forecast_confidence, percentage_predicted_bust: item.predicted_bust_cell_percentage,
    hotspot_count: item.hotspot_count }));
  return <div className="page"><div className="page-heading"><div><div className="eyebrow">{selectedState.toUpperCase()}</div><h1>Forecast <em>Overview</em></h1>
    <p>Can you trust this forecast? Explore model-derived reliability across the region.</p></div>
    {compatibleRuns.some(value => value < initialization) && <button className="soft-button" onClick={() => setCompareOpen(value => !value)}>{compareOpen ? 'Close comparison' : 'Run Comparison'} <ArrowRight size={16}/></button>}</div>
    {compareOpen && compatibleRuns.some(value => value < initialization) && <RunComparison initialization={initialization} lead={lead} options={compatibleRuns} selectedState={selectedStateProp} />}
    <div className="overview-grid"><section className="card map-card large"><div className="card-heading"><div><h3>Bust Probability Map</h3><span>Day {lead} · Valid {day.data?.records[0] ? dateUTC(day.data.records[0].valid_time) : '—'}</span></div>
      <div className="segmented"><button className={layer === 'bust_probability' ? 'active' : ''} onClick={() => setLayer('bust_probability')}>Probability</button><button className={layer === 'confidence_score' ? 'active' : ''} onClick={() => setLayer('confidence_score')}>Confidence</button></div></div>
      <State loading={day.loading} error={day.error} empty={!day.data?.records.length}><ForecastMap cells={day.data?.records || []} layer={layer} selectedState={selectedStateProp}
        selectedCell={selection.location} onCell={selection.selectLocation} focusRequest={selection.focusRequest} /></State></section>
      <div className="side-stack"><State loading={summary.loading || stateDay.loading} error={summary.error || stateDay.error} empty={!current || !highestCell}>
        {current && highestCell && <DayOverview summary={current} highest={highestCell}
          onFocus={() => selection.focusLocation(highestCell)}
          onExplain={() => { selection.focusLocation(highestCell); navigate('/explain'); }} />}</State>
        <State loading={day.loading} error={day.error} empty={!visibleCells.length}>{visibleCells.length > 0 && <WeatherMetrics cells={visibleCells} />}</State></div></div>
    <div className="bottom-grid"><section className="card"><div className="card-heading"><h3>Confidence Trend <span>({selectedState} · All Days)</span></h3><Link to="/analysis" aria-label="See forecast analysis"><ArrowRight size={17}/></Link></div>
      <State loading={stateSummary.loading} error={stateSummary.error}>{stateTimeline && <ConfidenceChart days={stateTimeline} active={lead} />}</State>
      {stateSummary.data && <small>Most uncertain state lead: Day {stateSummary.data.most_uncertain_lead_day} · {stateSummary.data.grid_cell_count} grid centers</small>}</section>
      <section className="card"><div className="card-heading"><h3>Highest-Risk Grid Cells <span>(Day {lead})</span></h3><Link to="/risk"><ArrowRight size={17}/></Link></div>
        <State loading={day.loading} error={day.error} empty={!top.length}><div className="rank-list">{top.map((cell, index) => <div key={`${cell.latitude}-${cell.longitude}`}><b className="rank">{index + 1}</b><MapPin size={17}/><span>{coordinates(cell.latitude, cell.longitude)}</span><strong>{percent(cell.bust_probability)}</strong><small className={`badge ${cell.is_bust_predicted ? 'risk' : 'neutral'}`}>{cell.is_bust_predicted ? 'Elevated' : 'Below threshold'}</small></div>)}</div></State></section>
      <section className="card brief-card"><div className="card-heading"><h3>Reliability Brief <span>({selectedState} · Day {lead})</span></h3><button title="Copy brief" aria-label="Copy brief" onClick={() => { if (stateBrief.data) void navigator.clipboard.writeText(stateBrief.data.text); }}><Copy size={17}/></button></div>
        <State loading={stateBrief.loading} error={stateBrief.error}>{stateBrief.data && <><p>{stateBrief.data.text}</p><small>{stateBrief.data.caveat}</small></>}</State>
        {stateDay.data && <div className="subtle-note">Expected absolute error: {stateDay.data.mean_expected_absolute_error_mm.toFixed(1)} mm · GEFS final 6h spread: {stateDay.data.mean_gefs_end_window_spread_6h_mm.toFixed(1)} mm</div>}
        <State loading={hotspots.loading} error={hotspots.error}>{hotspots.data && <div className="subtle-note">{visibleHotspots.length === 0 ? 'No elevated-risk hotspots for this day.' : `${visibleHotspots.length} hotspot${visibleHotspots.length === 1 ? '' : 's'} intersect the selected state.`}</div>}</State>
      </section></div>
  </div>;
}
