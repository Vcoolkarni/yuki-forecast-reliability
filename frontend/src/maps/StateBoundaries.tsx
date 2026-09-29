import { useEffect, useState } from 'react';
import { divIcon } from 'leaflet';
import { GeoJSON, Marker, Pane } from 'react-leaflet';
import type { FeatureCollection, Geometry } from 'geojson';

type StateProperties = { name: string; labelLatitude: number | null; labelLongitude: number | null };
export type StateBoundaryData = FeatureCollection<Geometry, StateProperties>;
const PATH = '/data/india-states.geojson';
let cached: Promise<StateBoundaryData> | null = null;

export function loadStateBoundaries(): Promise<StateBoundaryData> {
  if (!cached) cached = fetch(PATH).then(async response => {
    if (!response.ok) throw new Error(`State boundaries unavailable (${response.status})`);
    const data = await response.json() as StateBoundaryData;
    if (data.type !== 'FeatureCollection' || data.features.length !== 36 ||
        data.features.some(item => !item.properties?.name || !item.geometry))
      throw new Error('Bundled state boundary asset is invalid');
    return data;
  }).catch(error => { cached = null; throw error; });
  return cached;
}

export function useStateBoundaries() {
  const [state, setState] = useState<{ data: StateBoundaryData | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let cancelled = false;
    loadStateBoundaries().then(data => { if (!cancelled) setState({ data, error: null }); })
      .catch(error => { if (!cancelled) setState({ data: null, error: error.message }); });
    return () => { cancelled = true; };
  }, []);
  return state;
}

export function StateBoundaries({ data, selectedState }: { data: StateBoundaryData | null; selectedState?: string }) {
  if (!data) return null;
  const selected = data.features.find(item => item.properties.name === selectedState);
  return <Pane name="state-boundaries" style={{ zIndex: 450, pointerEvents: 'none' }}>
    <GeoJSON data={data} style={{ color: '#2f4137', weight: 1.45, opacity: selected ? .4 : .77, fillOpacity: 0, interactive: false }}
      attribution='State boundaries: geoBoundaries / DataMeet India, CC BY 2.5 IN' />
    {selected && <GeoJSON key={selectedState} data={selected} style={{ color: '#2f4137', weight: 3,
      opacity: 1, fillOpacity: 0, interactive: false }} />}
    {data.features.filter(item => item.properties.labelLatitude !== null && item.properties.labelLongitude !== null)
      .map(item => <Marker key={item.properties.name}
        position={[item.properties.labelLatitude!, item.properties.labelLongitude!]}
        icon={divIcon({ className: 'state-label', html: item.properties.name, iconSize: [110, 18], iconAnchor: [55, 9] })}
        interactive={false} />)}
  </Pane>;
}
