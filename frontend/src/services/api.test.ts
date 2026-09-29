import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './api';

afterEach(() => vi.unstubAllGlobals());
describe('typed API client', () => {
  it('requests the selected lead and forwards the actual response unchanged', async () => {
    const payload = { initialization_time: '2026-09-12T00:00:00Z', lead_day: 7, records: [] };
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
    vi.stubGlobal('fetch', fetcher);
    expect(await api.day('2026-09-12T00:00:00Z', 7)).toBe(payload);
    expect(fetcher.mock.calls[0][0]).toContain('/api/v2/forecast/2026-09-12T00%3A00%3A00Z/day/7');
  });
  it('surfaces a failed API instead of inventing dashboard data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    await expect(api.health()).rejects.toThrow(ApiError);
    await expect(api.health()).rejects.toThrow('API is unavailable');
  });
  it('keeps historical outcomes in the dedicated analog endpoint', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ analogs: [] }) });
    vi.stubGlobal('fetch', fetcher);
    await api.analogs('2026-09-12', 5, 22, 78);
    expect(fetcher.mock.calls[0][0]).toContain('/cell/analogs?');
    await api.cell('2026-09-12', 5, 22, 78);
    expect(fetcher.mock.calls[1][0]).not.toContain('/cell/analogs');
  });
});
