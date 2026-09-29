import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Risk } from './Risk';
import { SelectionProvider } from '../hooks/SelectionContext';

vi.mock('../components/ForecastMap', () => ({ ForecastMap: () => <div>Map</div> }));
afterEach(() => vi.unstubAllGlobals());

describe('risk empty state', () => {
  it('does not fabricate hotspots when the backend returns none', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => ({ ok: true,
      json: async () => url.endsWith('/hotspots') ? { hotspots: [] } : { records: [{
        latitude: 22, longitude: 78, bust_probability: .2, is_bust_predicted: false
      }] }
    })));
    render(<SelectionProvider><Risk initialization="2026-09-12T00:00:00Z" lead={4} /></SelectionProvider>);
    expect(await screen.findByText(/No contiguous elevated-risk hotspots/)).toBeTruthy();
    expect(screen.queryByText(/hotspot-1/)).toBeNull();
  });
});
