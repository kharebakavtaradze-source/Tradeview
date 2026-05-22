import { useRouter } from 'next/router';
import Link from 'next/link';

const NAV_ICONS = {
  home:    <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  search:  <><circle cx="11" cy="11" r="8" stroke="currentColor" fill="none" /><line x1="21" y1="21" x2="16.65" y2="16.65" stroke="currentColor" strokeLinecap="round" /></>,
  layers:  <><polygon points="12 2 2 7 12 12 22 7 12 2" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="2 17 12 22 22 17" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="2 12 12 17 22 12" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  folder:  <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  globe:   <><circle cx="12" cy="12" r="10" stroke="currentColor" fill="none" /><line x1="2" y1="12" x2="22" y2="12" stroke="currentColor" strokeLinecap="round" /><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" stroke="currentColor" fill="none" /></>,
  swap:    <><polyline points="17 1 21 5 17 9" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><path d="M3 11V9a4 4 0 014-4h14" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="7 23 3 19 7 15" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><path d="M21 13v2a4 4 0 01-4 4H3" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  bolt:    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  candle:  <><rect x="9" y="6" width="6" height="12" rx="1" stroke="currentColor" fill="none" /><line x1="12" y1="2" x2="12" y2="6" stroke="currentColor" strokeLinecap="round" /><line x1="12" y1="18" x2="12" y2="22" stroke="currentColor" strokeLinecap="round" /></>,
  spark:   <><polyline points="23 6 13.5 15.5 8.5 10.5 1 18" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="17 6 23 6 23 12" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  grid:    <><rect x="3" y="3" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /><rect x="14" y="3" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /><rect x="14" y="14" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /><rect x="3" y="14" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /></>,
  bell:    <><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><path d="M13.73 21a2 2 0 01-3.46 0" stroke="currentColor" fill="none" strokeLinecap="round" /></>,
};

function NavIcon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: 'block' }}>
      {NAV_ICONS[name] || <circle cx="12" cy="12" r="4" stroke="currentColor" fill="none" />}
    </svg>
  );
}

function PumpMark({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M12 1.5 C 12.7 7.6, 16.4 11.3, 22.5 12 C 16.4 12.7, 12.7 16.4, 12 22.5 C 11.3 16.4, 7.6 12.7, 1.5 12 C 7.6 11.3, 11.3 7.6, 12 1.5 Z" fill="var(--pump-lime)" />
    </svg>
  );
}

const NAV_ITEMS = [
  { href: '/',                  icon: 'home',   label: 'Dashboard' },
  { href: '/scanner-v2',        icon: 'search', label: 'Scanner' },
  { href: '/sectors',           icon: 'layers', label: 'Sectors' },
  { href: '/ai-journal',        icon: 'spark',  label: 'AI Journal' },
  null,
  { href: '/studio',            icon: 'grid',   label: 'Studio' },
];

function Sidebar() {
  const router = useRouter();
  return (
    <aside style={{
      width: 78, flexShrink: 0,
      background: 'var(--bg-1)',
      borderRight: '1px solid var(--stroke-soft)',
      padding: '18px 12px 14px',
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
      position: 'sticky', top: 0, alignSelf: 'flex-start',
      minHeight: '100vh', zIndex: 10,
    }}>
      <div style={{ padding: '4px 0 8px' }} title="Pump"><PumpMark size={24} /></div>
      {NAV_ITEMS.map((item, i) => {
        if (!item) return <div key={`d${i}`} style={{ height: 1, background: 'var(--stroke-soft)', width: 28, margin: '4px 0' }} />;
        const active = router.pathname === item.href;
        return (
          <Link key={item.href} href={item.href} title={item.label} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 42, height: 38, borderRadius: 8,
            background: active ? 'var(--pump-lime-soft)' : 'transparent',
            color: active ? 'var(--pump-lime)' : 'var(--ink-dim)',
            textDecoration: 'none', position: 'relative', transition: 'background 0.15s, color 0.15s',
          }}
          onMouseEnter={e => { if (!active) { e.currentTarget.style.background = 'var(--bg-2)'; e.currentTarget.style.color = 'var(--ink)'; }}}
          onMouseLeave={e => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--ink-dim)'; }}}
          >
            <NavIcon name={item.icon} size={18} />
            {active && <span style={{ position: 'absolute', left: -14, top: '50%', transform: 'translateY(-50%)', width: 4, height: 18, borderRadius: 2, background: 'var(--pump-lime)' }} />}
          </Link>
        );
      })}
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 42, height: 38, borderRadius: 8, color: 'var(--ink-dim)', cursor: 'pointer' }} title="Alerts">
        <NavIcon name="bell" size={18} />
      </div>
    </aside>
  );
}

export default function PumpLayout({ children, title, subtitle }) {
  const today = new Date();
  const dayName = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][today.getDay()];
  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-0)', display: 'flex' }}>
      <Sidebar />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <header style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 28px', borderBottom: '1px solid var(--stroke-soft)',
          background: 'var(--bg-0)', gap: 16, flexWrap: 'nowrap',
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)', marginBottom: 2 }}>{dayName}</div>
            <h1 style={{ margin: 0, fontSize: 21, fontWeight: 500, letterSpacing: '-0.02em', color: 'var(--ink)' }}>
              {title}{subtitle && <>{' '}<em style={{ fontFamily: 'var(--f-serif)', fontStyle: 'italic', color: 'var(--pump-lime)', fontWeight: 400 }}>{subtitle}</em></>}
            </h1>
          </div>
        </header>
        <main style={{ flex: 1 }}>
          {children}
        </main>
      </div>
    </div>
  );
}
