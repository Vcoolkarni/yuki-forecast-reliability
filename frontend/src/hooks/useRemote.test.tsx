import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useRemote } from './useRemote';

describe('request switching', () => {
  it('masks old values immediately and ignores a late response from the previous selection', async () => {
    const resolvers = new Map<number, (value: string) => void>();
    const load = (day: number) => new Promise<string>(resolve => resolvers.set(day, resolve));
    function View({ day }: { day: number }) {
      const remote = useRemote(() => load(day), [day]);
      return <div>{remote.loading ? 'Loading' : remote.data || remote.error}</div>;
    }
    const view = render(<View day={1} />);
    await act(async () => resolvers.get(1)?.('Day 1 value'));
    expect(screen.getByText('Day 1 value')).toBeTruthy();
    view.rerender(<View day={2} />);
    expect(screen.getByText('Loading')).toBeTruthy();
    view.rerender(<View day={5} />);
    await act(async () => resolvers.get(2)?.('Late Day 2 value'));
    expect(screen.queryByText('Late Day 2 value')).toBeNull();
    expect(screen.getByText('Loading')).toBeTruthy();
    await act(async () => resolvers.get(5)?.('Day 5 value'));
    expect(screen.getByText('Day 5 value')).toBeTruthy();
  });
});
