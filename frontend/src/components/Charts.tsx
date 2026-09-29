import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TimelinePoint } from '../types/api';

export function ConfidenceChart({ days, active }: { days: TimelinePoint[]; active: number }) {
  const data = days.map(day => ({ ...day, label: `Day ${day.lead_day}`, probability: day.mean_bust_probability * 100 }));
  return <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -25 }}>
    <defs><linearGradient id="confidenceFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#67af7f" stopOpacity={0.28}/><stop offset="100%" stopColor="#67af7f" stopOpacity={0.02}/></linearGradient></defs>
    <CartesianGrid vertical={false} stroke="#e6e9df" /><XAxis dataKey="label" tick={{ fontSize: 11 }} /><YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} />
    <Tooltip formatter={(value) => `${Number(value).toFixed(1)}%`} /><Area dataKey="mean_confidence" name="Confidence" stroke="#64a579" fill="url(#confidenceFill)" strokeWidth={2.5} dot={({ cx, cy, payload }) => <circle key={payload.label} cx={cx} cy={cy} r={payload.lead_day === active ? 5 : 3} fill={payload.lead_day === active ? '#eab74c' : '#64a579'} />} />
  </AreaChart></ResponsiveContainer></div>;
}

export function VariableChart({ values, unit }: { values: { lead_day: number; value: number }[]; unit: string }) {
  return <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><BarChart data={values} margin={{ top: 8, right: 16, bottom: 0, left: -24 }}>
    <CartesianGrid vertical={false} stroke="#e6e9df" /><XAxis dataKey="lead_day" tickFormatter={value => `D${value}`} tick={{ fontSize: 11 }} />
    <YAxis tick={{ fontSize: 11 }} /><Tooltip formatter={value => `${Number(value).toFixed(1)} ${unit}`} />
    <Bar dataKey="value" fill="#80b991" radius={[5, 5, 0, 0]} name="Forecast mean" />
  </BarChart></ResponsiveContainer></div>;
}

export function CellRiskChart({ values, active }: { values: { lead_day: number; bust_probability: number; confidence_score: number }[]; active: number }) {
  const data = values.map(value => ({ ...value, label: `Day ${value.lead_day}`, risk: value.bust_probability * 100 }));
  return <div className="chart-area"><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -24 }}>
    <CartesianGrid vertical={false} stroke="#e6e9df" /><XAxis dataKey="label" tick={{ fontSize: 11 }} /><YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 11 }} />
    <Tooltip formatter={value => `${Number(value).toFixed(1)}%`} />
    <ReferenceLine x={`Day ${active}`} stroke="#a9c2ae" strokeDasharray="4 3" />
    <Line dataKey="risk" name="Bust probability" stroke="#e95d55" strokeWidth={2.5} dot />
    <Line dataKey="confidence_score" name="Confidence" stroke="#69a97c" strokeWidth={2.5} dot />
  </LineChart></ResponsiveContainer></div>;
}
