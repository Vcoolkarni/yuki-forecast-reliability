import { useEffect, useMemo, useState } from 'react';
import { GeoJSON, ImageOverlay, MapContainer, Pane, Rectangle, TileLayer, Tooltip, useMap } from 'react-leaflet';
import { State } from './State';
import { useRemote } from '../hooks/useRemote';
import { api } from '../services/api';
import { coordinates, dateUTC, percentagePointDelta } from '../services/format';
import type { Comparison } from '../types/api';
import { buildRegularGrid, cellBounds, renderDisplayRaster } from '../maps/raster';
import { StateBoundaries, useStateBoundaries } from '../maps/StateBoundaries';
import { insideState, nearestStateCell, selectedStateGeometry, stateBounds, stateCells } from '../maps/stateClip';

type MapMode = 'current' | 'previous' | 'change';
function FitComparisonRegion({ bounds, selected }: { bounds: [[number, number], [number, number]]; selected: boolean }) {
  const map = useMap();
  useEffect(() => { if (selected) map.fitBounds(bounds, { padding: [20, 20], maxZoom: 9 }); },
    [map, bounds, selected]);
  return null;
}

function ComparisonMap({ data, mode, selectedState }: { data: Comparison; mode: MapMode; selectedState?: string }) {
  const grid = useMemo(() => buildRegularGrid(data.cells.map(cell => ({ latitude: cell.latitude, longitude: cell.longitude,
    value: mode === 'current' ? cell.current_bust_probability : mode === 'previous' ? cell.previous_bust_probability : cell.delta_bust_probability }))), [data, mode]);
  const boundaries = useStateBoundaries();
  const geometry = useMemo(() => selectedStateGeometry(boundaries.data, selectedState), [boundaries.data, selectedState]);
  const raster = useMemo(() => selectedState && !geometry ? '' : renderDisplayRaster(grid,
    mode === 'change' ? 'difference' : 'heat', 512, mode === 'change' ? undefined : [0, 1], geometry || undefined),
    [grid, mode, geometry, selectedState]);
  const imageBounds = useMemo<[[number, number], [number, number]]>(() =>
    [[grid.south, grid.west], [grid.north, grid.east]], [grid]);
  const bounds = useMemo(() => geometry ? stateBounds(geometry) : imageBounds, [geometry, imageBounds]);
  const visibleCells = useMemo(() => geometry ? stateCells(data.cells, geometry) : data.cells, [data.cells, geometry]);
  const [hovered, setHovered] = useState<Comparison['cells'][number] | null>(null);
  const maxDelta = Math.max(Math.abs(grid.min), Math.abs(grid.max)) * 100;
  if (selectedState && !geometry) return <div className="state-card">{boundaries.error || 'Loading selected state boundary…'}</div>;
  if (geometry && !visibleCells.length) return <div className="state-card">No co-located V2 grid center lies inside {selectedState}.</div>;
  return <div className="comparison-map"><MapContainer bounds={bounds} scrollWheelZoom={false} className="forecast-map">
    <FitComparisonRegion bounds={bounds} selected={!!geometry} />
    <TileLayer opacity={.66} attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    <Pane name="comparison-raster" style={{ zIndex: 410 }}><ImageOverlay url={raster} bounds={imageBounds} opacity={.82} interactive={false} /></Pane>
    <StateBoundaries data={boundaries.data} selectedState={selectedState} />
    {!geometry && <Pane name="comparison-domain" style={{ zIndex: 455, pointerEvents: 'none' }}><Rectangle bounds={imageBounds}
      pathOptions={{ color: '#30473a', weight: 1.7, opacity: .9, fillOpacity: 0, dashArray: '5 4', interactive: false }} /></Pane>}
    <Pane name="comparison-inspection" style={{ zIndex: 470 }}>{geometry ?
      <GeoJSON key={selectedState} data={geometry}
        style={{ color: '#000', weight: 0, opacity: 0, fillColor: '#000', fillOpacity: .001, interactive: true }}
        eventHandlers={{ mousemove: event => { const point = event.latlng;
          setHovered(insideState(geometry, point.lat, point.lng) ? nearestStateCell(visibleCells,
            point.lat, point.lng, grid.latitudes[1] - grid.latitudes[0], grid.longitudes[1] - grid.longitudes[0]) : null); },
          mouseout: () => setHovered(null) }} /> : visibleCells.map(cell => <Rectangle key={`${cell.latitude},${cell.longitude}`}
      bounds={cellBounds(grid, cell.latitude, cell.longitude)}
      pathOptions={{ color: '#000', weight: 0, opacity: 0, fillColor: '#000', fillOpacity: 0 }}>
      <Tooltip sticky><div className="cell-inspector"><strong>{coordinates(cell.latitude, cell.longitude)} · Day {cell.lead_day}</strong>
        <span>Previous risk: {(cell.previous_bust_probability * 100).toFixed(1)}%</span>
        <span>Current risk: {(cell.current_bust_probability * 100).toFixed(1)}%</span>
        <span>Change: {cell.delta_bust_probability >= 0 ? '+' : ''}{(cell.delta_bust_probability * 100).toFixed(1)} pp</span>
        <span>Confidence: {cell.previous_confidence.toFixed(1)}% → {cell.current_confidence.toFixed(1)}%</span>
        <span>{cell.state} bust status</span></div></Tooltip>
    </Rectangle>)}</Pane>
  </MapContainer><div className={`comparison-legend ${mode === 'change' ? 'diverging' : ''}`}>
      {mode === 'change' ? <><span>−{maxDelta.toFixed(1)} pp</span><i/><span>0</span><i/><span>+{maxDelta.toFixed(1)} pp</span></>
        : <><span>0%</span><i/><span>100%</span></>}
    </div>{hovered && geometry && <div className="map-selected-inspector"><div className="cell-inspector"><strong>{coordinates(hovered.latitude, hovered.longitude)} · Day {hovered.lead_day}</strong>
      <span>Previous risk: {(hovered.previous_bust_probability * 100).toFixed(1)}%</span>
      <span>Current risk: {(hovered.current_bust_probability * 100).toFixed(1)}%</span>
      <span>Change: {hovered.delta_bust_probability >= 0 ? '+' : ''}{(hovered.delta_bust_probability * 100).toFixed(1)} pp</span></div></div>}
    {boundaries.error && <div className="map-boundary-warning">State boundaries unavailable</div>}</div>;
}

export function RunComparison({ initialization, lead, options, selectedState }: { initialization: string; lead: number; options: string[]; selectedState?: string }) {
  const previousOptions = options.filter(value => value < initialization);
  const [preferred, setPreferred] = useState('');
  const [mode, setMode] = useState<MapMode>('change');
  const previous = previousOptions.includes(preferred) ? preferred : previousOptions.at(-1);
  const comparison = useRemote(signal => previous ? api.comparison(initialization, previous, lead, signal) : Promise.reject(new Error('No earlier available initialization can be compared.')),
    [initialization, previous, lead]);
  return <section className="card comparison-panel"><div className="card-heading"><div><h3>Run Comparison</h3><span>Current {dateUTC(initialization)} · model-domain totals · Day {lead}; map clipped to {selectedState || 'model domain'}</span></div>
    <label>Previous run <select value={previous || ''} onChange={event => setPreferred(event.target.value)} disabled={!previous}>
      {previousOptions.map(value => <option value={value} key={value}>{dateUTC(value)} · 00 UTC</option>)}</select></label></div>
    <State loading={comparison.loading} error={comparison.error} empty={!comparison.data}>{comparison.data && <div className="comparison-body">
      <div><div className="comparison-stats"><div><small>Mean risk change</small><strong className={comparison.data.mean_probability_delta > 0 ? 'text-risk' : 'text-good'}>{comparison.data.mean_probability_delta >= 0 ? '+' : ''}{(comparison.data.mean_probability_delta * 100).toFixed(1)} pp</strong></div>
        <div><small>Newly predicted bust cells</small><strong>{comparison.data.emerging_bust_cells}</strong></div><div><small>Resolved bust cells</small><strong>{comparison.data.resolved_bust_cells}</strong></div>
        <div><small>Persistent bust cells</small><strong>{comparison.data.persistent_bust_cells}</strong></div>
        <div><small>Mean confidence change</small><strong>{comparison.data.mean_confidence_delta >= 0 ? '+' : ''}{comparison.data.mean_confidence_delta.toFixed(1)} pp</strong></div>
        <div><small>Hotspot count change</small><strong>{comparison.data.hotspot_count_delta >= 0 ? '+' : ''}{comparison.data.hotspot_count_delta}</strong></div>
        <div><small>New hotspot regions</small><strong>{comparison.data.new_hotspot_regions}</strong></div>
        <div><small>Resolved hotspot regions</small><strong>{comparison.data.resolved_hotspot_regions}</strong></div></div>
        <div className="comparison-rank"><h4>Largest risk increases</h4>{comparison.data.largest_risk_increases.length ? comparison.data.largest_risk_increases.slice(0, 3).map(cell => <div key={`${cell.latitude},${cell.longitude}`}><span>{coordinates(cell.latitude, cell.longitude)}</span><b>+{percentagePointDelta(cell.current_bust_probability, cell.previous_bust_probability).toFixed(1)} pp</b></div>) : <p className="muted">No grid cells increased in predicted risk.</p>}</div>
        <div className="comparison-rank"><h4>Largest risk decreases</h4>{comparison.data.largest_risk_decreases.length ? comparison.data.largest_risk_decreases.slice(0, 3).map(cell => <div key={`${cell.latitude},${cell.longitude}`}><span>{coordinates(cell.latitude, cell.longitude)}</span><b className="text-good">{percentagePointDelta(cell.current_bust_probability, cell.previous_bust_probability).toFixed(1)} pp</b></div>) : <p className="muted">No grid cells decreased in predicted risk.</p>}</div>
        <p className="muted">These summary counts and changes cover the full model domain; the map is clipped to {selectedState || 'the model domain'}. Change compares calibrated predictions at the same lead and grid cells, not observed forecast error. New/resolved hotspot regions use non-overlapping hotspot bounding boxes.</p></div>
      <div><div className="segmented map-mode">{([['current', 'Current Risk'], ['previous', 'Previous Risk'], ['change', 'Risk Change']] as const).map(([key, label]) => <button key={key} className={mode === key ? 'active' : ''} onClick={() => setMode(key)}>{label}</button>)}</div><ComparisonMap data={comparison.data} mode={mode} selectedState={selectedState} /></div>
    </div>}</State></section>;
}
