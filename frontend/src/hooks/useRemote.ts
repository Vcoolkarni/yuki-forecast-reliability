import { useEffect, useState } from 'react';

export type Remote<T> = { data: T | null; loading: boolean; error: string | null };
export function useRemote<T>(load: (signal: AbortSignal) => Promise<T>, keys: unknown[]): Remote<T> {
  const key = JSON.stringify(keys);
  const [state, setState] = useState<Remote<T> & { key: string }>({ key, data: null, loading: true, error: null });
  useEffect(() => {
    const controller = new AbortController();
    setState({ key, data: null, loading: true, error: null });
    load(controller.signal).then(data => { if (!controller.signal.aborted) setState({ key, data, loading: false, error: null }); })
      .catch(error => { if (!controller.signal.aborted) setState({ key, data: null, loading: false, error: error.message || 'Request failed.' }); });
    return () => controller.abort();
  // The caller supplies dependencies; `load` closes over those values.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  // Mask stale data synchronously during render, before the new effect starts.
  return state.key === key ? state : { data: null, loading: true, error: null };
}
