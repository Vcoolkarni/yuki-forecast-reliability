import type { AnalogsResponse, BriefResponse, Comparison, DayResponse, GridCell,
  Health, HotspotsResponse, SummaryResponse, TimelineResponse, VariableTrendResponse,
  StatesResponse, StateSummaryResponse, EscalationResponse } from '../types/api';

const configuredBase = import.meta.env.VITE_API_BASE_URL;
// On a same-origin deployment (Vercel Services), API paths remain relative.
// Local development and explicitly configured cross-origin deployments retain their existing behavior.
const BASE = (configuredBase || (import.meta.env.PROD ? '' : 'http://127.0.0.1:8000')).replace(/\/$/, '');
export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
export async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try { response = await fetch(`${BASE}${path}`, { signal, headers: { Accept: 'application/json' } }); }
  catch (error) { if (signal?.aborted) throw error; throw new ApiError(0, 'The API is unavailable. Start the local backend and try again.'); }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try { const body = await response.json(); if (typeof body.detail === 'string') message = body.detail; } catch { /* Keep status message. */ }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}
const run = (value: string) => encodeURIComponent(value);
export const api = {
  health: (signal?: AbortSignal) => request<Health>('/api/v2/health', signal),
  states: (signal?: AbortSignal) => request<StatesResponse>('/api/v2/states', signal),
  stateSummary: (i: string, state: string, signal?: AbortSignal) => request<StateSummaryResponse>(`/api/v2/forecast/${run(i)}/state/${run(state)}/summary`, signal),
  stateDay: (i: string, state: string, d: number, signal?: AbortSignal) => request<StateSummaryResponse['days'][number]>(`/api/v2/forecast/${run(i)}/state/${run(state)}/day/${d}`, signal),
  stateBrief: (i: string, state: string, d: number, signal?: AbortSignal) => request<Pick<BriefResponse, 'text' | 'caveat'>>(`/api/v2/forecast/${run(i)}/state/${run(state)}/day/${d}/brief`, signal),
  summary: (i: string, signal?: AbortSignal) => request<SummaryResponse>(`/api/v2/forecast/${run(i)}/summary`, signal),
  day: (i: string, d: number, signal?: AbortSignal) => request<DayResponse>(`/api/v2/forecast/${run(i)}/day/${d}`, signal),
  hotspots: (i: string, d: number, signal?: AbortSignal) => request<HotspotsResponse>(`/api/v2/forecast/${run(i)}/day/${d}/hotspots`, signal),
  highestRisk: (i: string, d: number, signal?: AbortSignal) => request<GridCell>(`/api/v2/forecast/${run(i)}/day/${d}/highest-risk`, signal),
  cell: (i: string, d: number, lat: number, lon: number, signal?: AbortSignal) => request<GridCell>(`/api/v2/forecast/${run(i)}/cell?${new URLSearchParams({ latitude: String(lat), longitude: String(lon), lead_day: String(d) })}`, signal),
  timeline: (i: string, signal?: AbortSignal) => request<TimelineResponse>(`/api/v2/forecast/${run(i)}/timeline`, signal),
  comparison: (current: string, previous: string, d: number, signal?: AbortSignal) => request<Comparison>(`/api/v2/compare?${new URLSearchParams({ current_initialization: current, previous_initialization: previous, lead_day: String(d) })}`, signal),
  escalation: (current: string, previous: string, d: number, signal?: AbortSignal) => request<EscalationResponse>(`/api/v2/forecast/${run(current)}/day/${d}/escalation?${new URLSearchParams({ previous_initialization: previous })}`, signal),
  analogs: (i: string, d: number, lat: number, lon: number, limit = 5, signal?: AbortSignal) => request<AnalogsResponse>(`/api/v2/forecast/${run(i)}/cell/analogs?${new URLSearchParams({ latitude: String(lat), longitude: String(lon), lead_day: String(d), limit: String(limit) })}`, signal),
  brief: (i: string, d: number, signal?: AbortSignal) => request<BriefResponse>(`/api/v2/forecast/${run(i)}/day/${d}/brief`, signal),
  variableTrend: (i: string, field: string, signal?: AbortSignal) => request<VariableTrendResponse>(`/api/v2/forecast/${run(i)}/variables/trend?${new URLSearchParams({ field })}`, signal)
};
