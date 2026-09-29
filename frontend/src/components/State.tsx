export function State({ loading, error, empty, children }: { loading: boolean; error: string | null;
  empty?: boolean; children: React.ReactNode }) {
  if (loading) return <div className="state-card" role="status">Loading forecast data…</div>;
  if (error) return <div className="state-card state-error" role="alert">{error}</div>;
  if (empty) return <div className="state-card">No data is available for this selection.</div>;
  return <>{children}</>;
}
