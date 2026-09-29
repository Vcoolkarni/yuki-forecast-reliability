import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { Shell } from './Shell';
import type { Health } from '../types/api';

const health: Health = { api_ready: true, model_ready: true, forecast_ready: true, status: 'ready',
  model_id: 'test', decision_threshold: .3, features: [], cached_initializations: 0,
  available_initializations: ['2026-09-11T00:00:00Z', '2026-09-12T00:00:00Z'],
  grid: { south: 20, north: 24, west: 76, east: 80, latitude_step_degrees: .25, longitude_step_degrees: .25 } };

describe('shared navigation and selection', () => {
  it('offers exactly four primary routes and switches lead and available initialization', () => {
    const onLead = vi.fn(), onInitialization = vi.fn();
    render(<MemoryRouter><Routes><Route path="/" element={<Shell health={health} initialization={health.available_initializations[1]}
      onInitialization={onInitialization} lead={5} onLead={onLead} />}><Route index element={<div>Overview body</div>} /></Route></Routes></MemoryRouter>);
    expect(screen.getByRole('navigation', { name: 'Primary navigation' }).querySelectorAll('a')).toHaveLength(4);
    expect(screen.getAllByRole('button', { name: /Day \d+/ })).toHaveLength(10);
    fireEvent.click(screen.getByRole('button', { name: 'Day 7' }));
    expect(onLead).toHaveBeenCalledWith(7);
    fireEvent.change(screen.getByLabelText('Forecast initialization'), { target: { value: health.available_initializations[0] } });
    expect(onInitialization).toHaveBeenCalledWith(health.available_initializations[0]);
  });
  it('labels current and historical runs from API metadata when switching', () => {
    const demo = '2024-09-29T00:00:00Z', current = '2026-09-29T12:00:00Z';
    const mixed: Health = { ...health, available_initializations: [demo, current],
      primary_initialization: current, run_metadata: {
        [demo]: { run_kind: 'historical_demo', label: 'Historical demo · September 2024', initialization_utc: demo },
        [current]: { run_kind: 'current_forecast', label: 'Current forecast · latest successfully processed', initialization_utc: current }
      } };
    const view = render(<MemoryRouter><Shell health={mixed} initialization={current}
      onInitialization={vi.fn()} lead={1} onLead={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText(/Current forecast · latest successfully processed/)).toBeTruthy();
    expect(screen.getByRole('option', { name: /Historical demo/ })).toBeTruthy();
    view.rerender(<MemoryRouter><Shell health={mixed} initialization={demo}
      onInitialization={vi.fn()} lead={1} onLead={vi.fn()} /></MemoryRouter>);
    expect(screen.getByText(/Historical demo · September 2024/)).toBeTruthy();
  });
});
