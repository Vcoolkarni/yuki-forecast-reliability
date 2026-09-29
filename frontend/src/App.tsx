import { lazy, Suspense, useEffect, useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Shell } from './components/Shell';
import { State } from './components/State';
import { api } from './services/api';
import { SelectionProvider } from './hooks/SelectionContext';
import type { Health, StateInfo } from './types/api';
const Overview = lazy(() => import('./pages/Overview').then(module => ({ default: module.Overview })));
const Analysis = lazy(() => import('./pages/Analysis').then(module => ({ default: module.Analysis })));
const Risk = lazy(() => import('./pages/Risk').then(module => ({ default: module.Risk })));
const Explain = lazy(() => import('./pages/Explain').then(module => ({ default: module.Explain })));

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [initialization, setInitialization] = useState('');
  const [lead, setLead] = useState(5);
  const [states, setStates] = useState<StateInfo[]>([]);
  const [selectedState, setSelectedState] = useState('Madhya Pradesh');
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.health(controller.signal), api.states(controller.signal)]).then(([value, boundaries]) => {
      setHealth(value); setStates(boundaries.states);
      setInitialization(current => current || value.primary_initialization || value.available_initializations.at(-1) || ''); setLoading(false);
    })
      .catch(reason => { if (!controller.signal.aborted) { setError(reason.message); setLoading(false); } });
    return () => controller.abort();
  }, []);
  if (loading || error || !initialization || !health?.model_ready) {
    return <div className="boot-state"><div className="card"><img src="/logo.png" alt="Yuki" />
      <h1>Forecast reliability</h1><State loading={loading} error={error || (!health?.model_ready ? 'The local forecast API or model is not ready. Check /health and restart the backend.' : null)} empty={!initialization}>
        <p>Waiting for an available forecast initialization.</p></State>
      {!loading && <button className="soft-button" onClick={() => window.location.reload()}>Retry connection</button>}</div></div>;
  }
  return <BrowserRouter><SelectionProvider><Suspense fallback={<div className="state-card" role="status">Loading dashboard…</div>}><Routes><Route element={<Shell health={health} initialization={initialization} onInitialization={setInitialization} lead={lead} onLead={setLead} states={states} selectedState={selectedState} onState={setSelectedState} />}>
      <Route path="/" element={<Overview initialization={initialization} lead={lead} health={health} selectedState={selectedState} />} />
      <Route path="/overview" element={<Overview initialization={initialization} lead={lead} health={health} selectedState={selectedState} />} />
      <Route path="/analysis" element={<Analysis initialization={initialization} lead={lead} selectedState={selectedState} />} />
      <Route path="/risk" element={<Risk initialization={initialization} lead={lead} selectedState={selectedState} availableInitializations={health.available_initializations} runMetadata={health.run_metadata} />} />
      <Route path="/explain" element={<Explain initialization={initialization} lead={lead} selectedState={selectedState} />} />
    </Route></Routes></Suspense></SelectionProvider></BrowserRouter>;
}
