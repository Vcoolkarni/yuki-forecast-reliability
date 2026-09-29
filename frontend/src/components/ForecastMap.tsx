import { useEffect, useMemo, useState } from 'react';
import { GeoJSON, ImageOverlay, MapContainer, Pane, Polyline, Rectangle, TileLayer, Tooltip, useMap } from 'react-leaflet';
import type { GridCell, Hotspot } from '../types/api';
import { coordinates, layerValue, layers, percent, type WeatherLayer } from '../services/format';
import { buildRegularGrid, cellBounds, renderDisplayRaster, renderStateHotspots,
  renderSelectedCellOutline } from '../maps/raster';
import { hotspotOutline } from '../maps/hotspotGeometry';
import { StateBoundaries, useStateBoundaries } from '../maps/StateBoundaries';
import { insideState, nearestStateCell, selectedStateGeometry, stateBounds, stateCells, stateHotspots } from '../maps/stateClip';

const EMPTY_HOTSPOTS: Hotspot[] = [];

function FitRegion({ bounds, selected }: { bounds: [[number, number], [number, number]]; selected: boolean }) {
  const map = useMap();
  useEffect(() => { map.fitBounds(bounds, selected ? { padding: [20, 20], maxZoom: 9 } :
    { padding: [12, 12] }); }, [map, bounds, selected]);
  return null;
}

function FocusRegion({ cell, request }: { cell?: { latitude: number; longitude: number } | null; request?: number }) {
  const map = useMap();
  useEffect(() => { if (cell && request) map.panTo([cell.latitude, cell.longitude], { animate: true }); },
    [map, cell?.latitude, cell?.longitude, request]);
  return null;
}

function CellInspector({ cell, layer, hotspot }: { cell: GridCell; layer: WeatherLayer; hotspot?: Hotspot }) {
  const info = layers.find(item => item.key === layer)!;
  return <div className="cell-inspector"><strong>{coordinates(cell.latitude, cell.longitude)}</strong>
    <span>Day {cell.lead_day} · {info.label}: {layerValue(cell, layer).toFixed(1)} {info.unit}</span>
    <span>Bust probability: {percent(cell.bust_probability, 1)}</span>
    <span>Model-derived confidence: {cell.confidence_score.toFixed(1)}%</span>
    <span>{cell.is_bust_predicted ? 'Predicted bust' : 'Below predicted-bust threshold'}</span>
    {hotspot && <span className="inspector-hotspot"><b>{hotspot.hotspot_id}</b> · {hotspot.number_of_cells} cells · centroid {coordinates(hotspot.centroid_latitude, hotspot.centroid_longitude)} · mean {percent(hotspot.mean_bust_probability, 1)} · max {percent(hotspot.max_bust_probability, 1)}</span>}
  </div>;
}

export function ForecastMap({ cells, layer = 'bust_probability', hotspots = EMPTY_HOTSPOTS, selectedHotspot,
  selectedCell, onCell, onHotspot, focusRequest, selectedState }: { cells: GridCell[]; layer?: WeatherLayer; hotspots?: Hotspot[];
  selectedHotspot?: string | null; selectedCell?: { latitude: number; longitude: number } | null;
  onCell?: (cell: GridCell) => void; onHotspot?: (hotspot: Hotspot) => void; focusRequest?: number;
  selectedState?: string }) {
  const grid = useMemo(() => buildRegularGrid(cells.map(cell => ({ latitude: cell.latitude,
    longitude: cell.longitude, value: layerValue(cell, layer) }))), [cells, layer]);
  const boundaries = useStateBoundaries();
  const geometry = useMemo(() => selectedStateGeometry(boundaries.data, selectedState), [boundaries.data, selectedState]);
  const visibleCells = useMemo(() => geometry ? stateCells(cells, geometry) : cells, [cells, geometry]);
  const visibleHotspots = useMemo(() => geometry ? stateHotspots(hotspots, cells, geometry) : hotspots,
    [hotspots, cells, geometry]);
  const [hovered, setHovered] = useState<GridCell | null>(null);
  useEffect(() => setHovered(null), [selectedState]);
  const fixedScale = layer === 'bust_probability' || layer === 'confidence_score';
  const visibleValues = visibleCells.map(cell => layerValue(cell, layer));
  const minimum = fixedScale ? 0 : visibleValues.length ? Math.min(...visibleValues) : grid.min;
  const maximum = fixedScale ? 100 : visibleValues.length ? Math.max(...visibleValues) : grid.max;
  const raster = useMemo(() => selectedState && !geometry ? '' : renderDisplayRaster(grid,
    layer === 'confidence_score' ? 'confidence' : 'heat', 512, [minimum, maximum], geometry || undefined),
    [grid, layer, minimum, maximum, geometry, selectedState]);
  const hotspotRaster = useMemo(() => geometry && visibleHotspots.length ?
    renderStateHotspots(grid, visibleHotspots, geometry, selectedHotspot) : '',
    [grid, visibleHotspots, geometry, selectedHotspot]);
  const imageBounds = useMemo<[[number, number], [number, number]]>(() => [[grid.south, grid.west], [grid.north, grid.east]], [grid]);
  const bounds = useMemo(() => geometry ? stateBounds(geometry) : imageBounds, [geometry, imageBounds]);
  const info = layers.find(item => item.key === layer)!;
  const latitudeStep = grid.latitudes[1] - grid.latitudes[0];
  const longitudeStep = grid.longitudes[1] - grid.longitudes[0];
  const hotspotByCell = useMemo(() => {
    const lookup = new Map<string, Hotspot>();
    for (const hotspot of visibleHotspots) for (const member of hotspot.member_cells)
      lookup.set(`${member.latitude}|${member.longitude}`, hotspot);
    return lookup;
  }, [visibleHotspots]);
  const selectedRecord = selectedCell && visibleCells.find(cell => cell.latitude === selectedCell.latitude && cell.longitude === selectedCell.longitude);
  const selectedOutline = useMemo(() => geometry && selectedRecord ?
    renderSelectedCellOutline(grid, selectedRecord.latitude, selectedRecord.longitude, geometry) : '',
    [geometry, selectedRecord, grid]);
  if (selectedState && !geometry) return <div className="state-card">{boundaries.error ||
    (boundaries.data ? `Selected state boundary is unavailable: ${selectedState}` : 'Loading selected state boundary…')}</div>;
  if (geometry && !visibleCells.length) return <div className="state-card">No V2 0.5° grid center lies inside {selectedState}; no state forecast is inferred.</div>;
  return <div className="map-wrap">
    <MapContainer center={[(grid.south + grid.north) / 2, (grid.west + grid.east) / 2]} zoom={7}
      scrollWheelZoom={false} className="forecast-map" zoomControl>
      <TileLayer opacity={.66} attribution='&copy; OpenStreetMap contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <FitRegion bounds={bounds} selected={!!geometry} /><FocusRegion cell={selectedCell} request={focusRequest} />
      <Pane name="weather-raster" style={{ zIndex: 410 }}>
        <ImageOverlay url={raster} bounds={imageBounds} opacity={.82} interactive={false} />
      </Pane>
      <Pane name="hotspot-fill" style={{ zIndex: 425, pointerEvents: 'none' }}>
        {geometry ? hotspotRaster && <ImageOverlay url={hotspotRaster} bounds={imageBounds} interactive={false} /> : visibleHotspots.flatMap(hotspot => hotspot.member_cells.map(member => <Rectangle
          key={`${hotspot.hotspot_id}-${member.latitude}-${member.longitude}`}
          bounds={cellBounds(grid, member.latitude, member.longitude)}
          pathOptions={{ stroke: false, fillColor: '#e9554c', fillOpacity: selectedHotspot === hotspot.hotspot_id ? .25 : selectedHotspot ? .05 : .13, interactive: false }} />))}
      </Pane>
      {!geometry && <Pane name="hotspot-outline" style={{ zIndex: 440, pointerEvents: 'none' }}>
        {visibleHotspots.map(hotspot => <Polyline key={hotspot.hotspot_id}
          positions={hotspotOutline(hotspot, latitudeStep, longitudeStep, grid)}
          pathOptions={{ color: '#c9504b', weight: selectedHotspot === hotspot.hotspot_id ? 3 : 1.8,
            opacity: selectedHotspot && selectedHotspot !== hotspot.hotspot_id ? .35 : .9, interactive: false }} />)}
      </Pane>}
      <StateBoundaries data={boundaries.data} selectedState={selectedState} />
      {!geometry && <Pane name="domain-outline" style={{ zIndex: 455, pointerEvents: 'none' }}>
        <Rectangle bounds={imageBounds} pathOptions={{ color: '#30473a', weight: 1.7, opacity: .9,
          fillOpacity: 0, dashArray: '5 4', interactive: false }} />
      </Pane>}
      <Pane name="grid-inspection" style={{ zIndex: 470 }}>
        {geometry ? <GeoJSON key={selectedState} data={geometry}
          style={{ color: '#000', weight: 0, opacity: 0, fillColor: '#000', fillOpacity: .001, interactive: true }}
          eventHandlers={{ mousemove: event => { const point = event.latlng;
            setHovered(insideState(geometry, point.lat, point.lng) ?
              nearestStateCell(visibleCells, point.lat, point.lng, latitudeStep, longitudeStep) : null); },
            mouseout: () => setHovered(null),
            click: event => { const point = event.latlng;
              if (!insideState(geometry, point.lat, point.lng)) return;
              const cell = nearestStateCell(visibleCells, point.lat, point.lng, latitudeStep, longitudeStep);
              if (!cell) return;
              onCell?.(cell);
              const hotspot = hotspotByCell.get(`${cell.latitude}|${cell.longitude}`);
              if (hotspot) onHotspot?.(hotspot);
            } }} /> : visibleCells.map(cell => {
          const hotspot = hotspotByCell.get(`${cell.latitude}|${cell.longitude}`);
          return <Rectangle key={`${cell.latitude}-${cell.longitude}`}
            bounds={cellBounds(grid, cell.latitude, cell.longitude)}
            pathOptions={{ color: '#000', weight: 0, opacity: 0, fillColor: '#000', fillOpacity: 0 }}
            eventHandlers={{ click: () => { onCell?.(cell); if (hotspot) onHotspot?.(hotspot); } }}>
            <Tooltip sticky direction="top" opacity={.96}><CellInspector cell={cell} layer={layer} hotspot={hotspot} /></Tooltip>
          </Rectangle>;
        })}
      </Pane>
      {selectedRecord && <Pane name="selected-cell" style={{ zIndex: 480, pointerEvents: 'none' }}>
        {geometry ? <ImageOverlay url={selectedOutline} bounds={imageBounds} interactive={false} /> :
          <Rectangle bounds={cellBounds(grid, selectedRecord.latitude, selectedRecord.longitude)}
            pathOptions={{ color: '#223a2c', weight: 2.5, fillOpacity: 0, interactive: false }} />}
      </Pane>}
    </MapContainer>
    {(hovered || selectedRecord) && <div className="map-selected-inspector"><CellInspector cell={(hovered || selectedRecord)!} layer={layer}
      hotspot={hotspotByCell.get(`${(hovered || selectedRecord)!.latitude}|${(hovered || selectedRecord)!.longitude}`)} /></div>}
    <div className="map-domain-tag">{selectedState ? `${selectedState} · ${visibleCells.length} original grid centers` : `Model domain · ${grid.latitudes.length} × ${grid.longitudes.length} source cells`}</div>
    {boundaries.error && <div className="map-boundary-warning">State boundaries unavailable</div>}
    <div className={`map-legend ${layer === 'confidence_score' ? 'confidence' : ''}`}><strong>{info.label}</strong><div className="legend-body"><span>{minimum.toFixed(1)} {info.unit}</span><div className="legend-ramp"/><span>{maximum.toFixed(1)} {info.unit}</span></div>
      <small>Display-smoothed only · inspect original grid values on hover</small></div>
  </div>;
}
