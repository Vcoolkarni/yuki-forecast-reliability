import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RunComparison } from './RunComparison';

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Pane: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Rectangle: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TileLayer: () => null, ImageOverlay: () => null, useMap: () => ({ fitBounds: vi.fn() })
}));
vi.mock('../maps/StateBoundaries', () => ({ StateBoundaries: () => null,
  useStateBoundaries: () => ({ data: null, error: null }) }));
vi.mock('../maps/raster', async importOriginal => {
  const original = await importOriginal<typeof import('../maps/raster')>();
  return { ...original, renderDisplayRaster: () => 'data:image/png;base64,test' };
});
afterEach(() => vi.unstubAllGlobals());

describe('run comparison panel', () => {
  it('uses the actual endpoint delta and switches current/previous/zero-centered change modes', async () => {
    const cells = [20, 20.25].flatMap(latitude => [76, 76.25].map(longitude => ({
      latitude, longitude, lead_day: 5, previous_bust_probability: .31,
      current_bust_probability: .64, delta_bust_probability: .33,
      previous_confidence: 69, current_confidence: 36, delta_confidence: -33, state: 'emerging'
    })));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      current_initialization: '2026-09-12T00:00:00Z', previous_initialization: '2026-09-11T00:00:00Z',
      lead_day: 5, number_of_cells: 4, mean_probability_delta: .33, mean_confidence_delta: -33,
      emerging_bust_cells: 4, resolved_bust_cells: 0, persistent_bust_cells: 0,
      previous_hotspot_count: 0, current_hotspot_count: 1, hotspot_count_delta: 1,
      new_hotspot_regions: 1, resolved_hotspot_regions: 0,
      largest_risk_increases: cells.slice(0, 1), largest_risk_decreases: [], cells
    }) }));
    render(<RunComparison initialization="2026-09-12T00:00:00Z" lead={5}
      options={['2026-09-11T00:00:00Z', '2026-09-12T00:00:00Z']} />);
    expect(await screen.findByText('Mean risk change')).toBeTruthy();
    expect(screen.getByText(/model-domain totals/)).toBeTruthy();
    expect(screen.getAllByText('+33.0 pp').length).toBeGreaterThan(0);
    expect(screen.getByText('Newly predicted bust cells')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Risk Change' }).className).toContain('active');
    fireEvent.click(screen.getByRole('button', { name: 'Current Risk' }));
    expect(screen.getByRole('button', { name: 'Current Risk' }).className).toContain('active');
    fireEvent.click(screen.getByRole('button', { name: 'Previous Risk' }));
    expect(screen.getByRole('button', { name: 'Previous Risk' }).className).toContain('active');
    fireEvent.click(screen.getByRole('button', { name: 'Risk Change' }));
    expect(screen.getByText(/−33.0 pp/)).toBeTruthy();
  });
});
