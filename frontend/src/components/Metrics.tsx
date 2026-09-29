import { AlertTriangle, CloudRain, Droplets, Gauge, Thermometer, Wind } from 'lucide-react';
import type { DaySummary, GridCell } from '../types/api';
import { confidencePercent, coordinates, kelvinToCelsius, metersPerSecondToKmh, percent } from '../services/format';

export function Metric({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: 'risk' | 'good' }) {
  return <div className={`metric ${tone || ''}`}><small>{label}</small><strong>{value}</strong>{note && <span>{note}</span>}</div>;
}

export function DayOverview({ summary, highest, onFocus, onExplain }: { summary: DaySummary; highest: GridCell;
  onFocus?: () => void; onExplain?: () => void }) {
  return <section className="card overview-card"><h3>Day {summary.lead_day} Overview</h3>
    <div className="overview-metrics"><div className="confidence-big"><div className="gauge-ring" style={{ '--gauge': `${summary.mean_confidence}%` } as React.CSSProperties}>
      <span>{confidencePercent(summary.mean_confidence)}</span></div><strong>Mean confidence</strong><small>Model-derived, not forecast correctness</small></div>
      <div className="metric-list"><div><AlertTriangle size={19} /><span><strong>{percent(summary.maximum_bust_probability)}</strong><small>Highest bust probability<br/>{coordinates(highest.latitude, highest.longitude)}</small></span></div>
        <div><Gauge size={19}/><span><strong>{summary.hotspot_count}</strong><small>Elevated-risk hotspots</small></span></div>
        <div><Droplets size={19}/><span><strong>{percent(summary.mean_bust_probability, 1)}</strong><small>Mean bust probability</small></span></div>
        <div><CloudRain size={19}/><span><strong>{summary.percentage_predicted_bust.toFixed(1)}%</strong><small>Grid cells predicted as busts</small></span></div>
      </div></div><div className="overview-actions"><button onClick={onFocus}>Focus highest risk</button><button onClick={onExplain}>Explain this risk</button></div></section>;
}

export function WeatherMetrics({ cells }: { cells: GridCell[] }) {
  const mean = (selector: (cell: GridCell) => number) => cells.reduce((total, cell) => total + selector(cell), 0) / cells.length;
  const values = [
    [Thermometer, 'Temperature', `${mean(cell => kelvinToCelsius(cell.forecast_temperature_2m)).toFixed(1)}°C`],
    [Droplets, 'Relative humidity', `${mean(cell => cell.forecast_relative_humidity_2m).toFixed(0)}%`],
    [Wind, 'Wind speed', `${mean(cell => metersPerSecondToKmh(cell.forecast_wind_speed_10m)).toFixed(1)} km/h`],
    [CloudRain, 'Precipitation', `${mean(cell => cell.forecast_precipitation).toFixed(1)} mm`]
  ] as const;
  return <section className="card weather-card"><h3>Regional forecast values</h3><div className="weather-metrics">{values.map(([Icon, name, value]) =>
    <div key={name}><Icon size={22}/><strong>{value}</strong><small>{name}</small></div>)}</div></section>;
}
