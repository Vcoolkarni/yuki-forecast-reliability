import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { State } from './State';

describe('loading/error/empty states', () => {
  it('shows loading, API failure, and unavailable data without placeholders', () => {
    const view = render(<State loading error={null}>Real content</State>);
    expect(screen.getByRole('status').textContent).toContain('Loading');
    view.rerender(<State loading={false} error="API unavailable">Real content</State>);
    expect(screen.getByRole('alert').textContent).toContain('API unavailable');
    view.rerender(<State loading={false} error={null} empty>Real content</State>);
    expect(screen.getByText(/No data is available/)).toBeTruthy();
    expect(screen.queryByText('Real content')).toBeNull();
  });
});
