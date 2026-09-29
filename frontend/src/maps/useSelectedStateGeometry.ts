import { useEffect, useState } from 'react';
import { loadStateBoundaries } from './StateBoundaries';
import { selectedStateGeometry, type StateGeometry } from './stateClip';

/** Optional for legacy isolated component tests; the app always supplies a state. */
export function useSelectedStateGeometry(name?: string): StateGeometry | null {
  const [geometry, setGeometry] = useState<StateGeometry | null>(null);
  useEffect(() => {
    let active = true;
    if (!name) return () => { active = false; };
    setGeometry(null);
    loadStateBoundaries().then(data => { if (active) setGeometry(selectedStateGeometry(data, name)); })
      .catch(() => { if (active) setGeometry(null); });
    return () => { active = false; };
  }, [name]);
  return geometry;
}
