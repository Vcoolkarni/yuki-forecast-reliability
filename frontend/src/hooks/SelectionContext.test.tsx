import { fireEvent, render, screen } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { SelectionProvider, useSelection } from './SelectionContext';

function Choose() {
  const selection = useSelection();
  return <><button onClick={() => selection.selectLocation({ latitude: 22.5, longitude: 78 })}>Choose cell</button>
    <Link to="/explain">Why This Forecast?</Link></>;
}
function ExplainSelection() {
  const selection = useSelection();
  return <div>Selected: {selection.location?.latitude}, {selection.location?.longitude}</div>;
}
describe('cross-page location continuity', () => {
  it('persists the same original grid cell across route navigation', () => {
    render(<MemoryRouter><SelectionProvider><Routes><Route path="/" element={<Choose/>}/>
      <Route path="/explain" element={<ExplainSelection/>}/></Routes></SelectionProvider></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Choose cell' }));
    fireEvent.click(screen.getByRole('link', { name: 'Why This Forecast?' }));
    expect(screen.getByText('Selected: 22.5, 78')).toBeTruthy();
  });
});
