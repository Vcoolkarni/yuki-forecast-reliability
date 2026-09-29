import { createContext, useContext, useMemo, useState } from 'react';

export type SelectedLocation = { latitude: number; longitude: number };
type Selection = { location: SelectedLocation | null; focusRequest: number;
  selectLocation: (value: SelectedLocation) => void; focusLocation: (value: SelectedLocation) => void };
const Context = createContext<Selection | null>(null);

export function SelectionProvider({ children }: { children: React.ReactNode }) {
  const [location, setLocation] = useState<SelectedLocation | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const value = useMemo<Selection>(() => ({ location, focusRequest,
    selectLocation: value => setLocation({ latitude: value.latitude, longitude: value.longitude }),
    focusLocation: value => { setLocation({ latitude: value.latitude, longitude: value.longitude });
      setFocusRequest(current => current + 1); }
  }), [location, focusRequest]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSelection(): Selection {
  const value = useContext(Context);
  if (!value) throw new Error('Location selection requires SelectionProvider');
  return value;
}
