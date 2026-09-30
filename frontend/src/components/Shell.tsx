import { BarChart3, CalendarDays, CircleHelp, House, MapPin, ShieldAlert } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import type { Health, StateInfo } from '../types/api';

export function Shell({ health, initialization, onInitialization, lead, onLead, states = [], selectedState, onState }: {
  health: Health; initialization: string; onInitialization: (value: string) => void;
  lead: number; onLead: (value: number) => void; states?: StateInfo[];
  selectedState?: string; onState?: (value: string) => void;
}) {
  const region = health.grid ? `${health.grid.south.toFixed(0)}–${health.grid.north.toFixed(0)}°N, ${health.grid.west.toFixed(0)}–${health.grid.east.toFixed(0)}°E` : 'Forecast grid';
  const resolution = health.grid?.latitude_step_degrees && health.grid?.longitude_step_degrees
    ? `${health.grid.latitude_step_degrees.toFixed(2)}° × ${health.grid.longitude_step_degrees.toFixed(2)}° grid` : 'Grid resolution unavailable';
  const run = health.run_metadata?.[initialization];
  const compactRunLabel = (value: string) => {
    const date = new Date(value);
    const kind = health.run_metadata?.[value]?.run_kind;
    const prefix = kind === 'current_forecast' ? 'Current' : kind === 'historical_demo' ? 'Demo' : 'Forecast';
    const day = date.toLocaleDateString('en-GB', { timeZone: 'UTC', day: 'numeric', month: 'short' });
    const hour = date.toLocaleTimeString('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', hour12: false });
    return `${prefix} · ${day} ${hour}Z`;
  };
  const links = [ ['/', House, 'Overview'], ['/analysis', BarChart3, 'Forecast Analysis'],
    ['/risk', MapPin, 'Risk & Hotspots'], ['/explain', CircleHelp, 'Why This Forecast?'] ] as const;
  return <div className="app-shell">
    <aside className="sidebar glass">
      <NavLink to="/" className="brand"><img src="/logo.png" alt="Yuki" /></NavLink>
      <nav aria-label="Primary navigation">{links.map(([to, Icon, label]) =>
        <NavLink end={to === '/'} key={to} to={to} aria-label={label} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
          <Icon size={19} strokeWidth={2} /><span>{label}</span>
        </NavLink>)}</nav>
      <div className="sidebar-foot"><img src="/logo.png" alt="" /><span>Forecast reliability<br/><small>{region} · {resolution}</small></span></div>
    </aside>
    <div className="workspace">
      <header className="topbar">
        <div className="region-search"><MapPin size={18} /><span>India · {region} · {run?.label || health.source_label || 'Forecast feed'}</span></div>
        {states.length > 0 && <label className="init-control"><MapPin size={20} /><span><small>State / UT</small><select value={selectedState} onChange={event => onState?.(event.target.value)} aria-label="State or Union Territory">
          {states.map(item => <option key={item.name} value={item.name}>{item.name}{item.has_grid_centers ? '' : ' · no 0.5° grid center'}</option>)}
        </select></span></label>}
        <label className="init-control"><CalendarDays size={20} /><span><small>Forecast initialization</small><select value={initialization} onChange={event => onInitialization(event.target.value)} aria-label="Forecast initialization">
          {health.available_initializations.map(value => <option key={value} value={value}>{health.run_metadata?.[value]?.run_kind === 'current_forecast' ? 'Current forecast · ' : health.run_metadata?.[value]?.run_kind === 'historical_demo' ? 'Historical demo · ' : ''}{new Date(value).toLocaleString('en-GB', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' })} UTC</option>)}
        </select><select className="run-mobile" value={initialization} onChange={event => onInitialization(event.target.value)} aria-label="Forecast initialization (mobile)">
          {health.available_initializations.map(value => <option key={value} value={value}>{compactRunLabel(value)}</option>)}
        </select></span></label>
      </header>
      <main><div className="context-row"><div className="chips"><span><MapPin size={16} /> {region}</span><span>{resolution}</span><span>10-day forecast horizon</span></div>
        <div className="day-tabs" role="group" aria-label="Forecast lead day">{Array.from({ length: 10 }, (_, index) => index + 1).map(day =>
          <button key={day} className={lead === day ? 'selected' : ''} onClick={() => onLead(day)}>Day {day}</button>)}</div></div>
        <Outlet /></main>
      <footer className="footer-note"><ShieldAlert size={14} /> Model-derived guidance. Use alongside the underlying NWP forecast.</footer>
    </div>
  </div>;
}
