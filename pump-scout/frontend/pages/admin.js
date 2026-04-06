import { useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function AdminPage() {
  const [symbol, setSymbol] = useState('KPTI');
  const [massiveResult, setMassiveResult] = useState(null);
  const [enrichResult, setEnrichResult] = useState(null);
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});

  async function call(key, url) {
    setLoading(l => ({ ...l, [key]: true }));
    setError(e => ({ ...e, [key]: null }));
    try {
      const res = await fetch(url);
      const data = await res.json();
      if (key === 'massive') setMassiveResult(data);
      else if (key === 'enrich') setEnrichResult(data);
    } catch (err) {
      setError(e => ({ ...e, [key]: err.message }));
    } finally {
      setLoading(l => ({ ...l, [key]: false }));
    }
  }

  return (
    <>
      <Head><title>Admin — Pump Scout</title></Head>
      <div style={{ maxWidth: 800, margin: '0 auto', padding: '24px 16px', fontFamily: "'JetBrains Mono', monospace", color: '#e0e0e0', background: '#0a0a0f', minHeight: '100vh' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
          <Link href="/" style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', textDecoration: 'none' }}>← back</Link>
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 800, letterSpacing: '0.06em' }}>ADMIN PANEL</h1>
          <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginLeft: 'auto' }}>backend: {API_URL}</span>
        </div>

        {/* Test Massive */}
        <section style={{ marginBottom: 32, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: 16 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.6)' }}>TEST MASSIVE API</h2>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              placeholder="Symbol (e.g. KPTI)"
              style={{ flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0', fontFamily: 'inherit', fontSize: 12 }}
            />
            <button
              onClick={() => call('massive', `${API_URL}/api/admin/test-massive?symbol=${symbol}`)}
              disabled={loading.massive}
              style={{ background: '#4488ff', border: 'none', borderRadius: 4, padding: '6px 16px', color: '#fff', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700 }}
            >
              {loading.massive ? 'Testing…' : 'Test'}
            </button>
          </div>
          {error.massive && <div style={{ color: '#ff6b6b', fontSize: 11, marginBottom: 8 }}>Error: {error.massive}</div>}
          {massiveResult && (
            <pre style={{ margin: 0, fontSize: 10, color: '#a0e0a0', background: 'rgba(0,0,0,0.3)', borderRadius: 4, padding: 10, overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(massiveResult, null, 2)}
            </pre>
          )}
        </section>

        {/* Enrich Sectors */}
        <section style={{ marginBottom: 32, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: 16 }}>
          <h2 style={{ margin: '0 0 8px', fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.6)' }}>ENRICH SECTORS</h2>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>
            Runs Massive enrichment in background (1 call per 15s, rate-limited). Returns immediately.
          </p>
          <button
            onClick={() => call('enrich', `${API_URL}/api/admin/enrich-sectors`)}
            disabled={loading.enrich}
            style={{ background: 'rgba(68,255,100,0.15)', border: '1px solid rgba(68,255,100,0.3)', borderRadius: 4, padding: '6px 16px', color: '#44ff64', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700 }}
          >
            {loading.enrich ? 'Starting…' : 'Run Enrichment'}
          </button>
          {error.enrich && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.enrich}</div>}
          {enrichResult && (
            <pre style={{ margin: '12px 0 0', fontSize: 10, color: '#a0e0a0', background: 'rgba(0,0,0,0.3)', borderRadius: 4, padding: 10, overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(enrichResult, null, 2)}
            </pre>
          )}
        </section>

        {/* Direct backend links */}
        <section style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: 16 }}>
          <h2 style={{ margin: '0 0 8px', fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', color: 'rgba(255,255,255,0.6)' }}>QUICK LINKS (BACKEND)</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {[
              [`/api/admin/test-massive?symbol=${symbol}`, 'Test Massive for current symbol'],
              ['/api/admin/enrich-sectors', 'Trigger sector enrichment'],
              ['/api/admin/rotate-data', 'Rotate old data'],
              ['/health', 'Health check'],
            ].map(([path, label]) => (
              <div key={path} style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <a
                  href={`${API_URL}${path}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ fontSize: 10, color: '#4488ff', fontFamily: 'monospace' }}
                >
                  {API_URL}{path}
                </a>
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>— {label}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
