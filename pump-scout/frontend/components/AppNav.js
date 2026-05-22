import Link from 'next/link';
import { useRouter } from 'next/router';

// 4-point star SVG from PUMP design system
function PumpMark({ size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className="logo-mark">
      <path
        d="M12 1.5 C 12.7 7.6, 16.4 11.3, 22.5 12 C 16.4 12.7, 12.7 16.4, 12 22.5 C 11.3 16.4, 7.6 12.7, 1.5 12 C 7.6 11.3, 11.3 7.6, 12 1.5 Z"
        fill="var(--pump-lime)"
      />
    </svg>
  );
}

const NAV_LINKS = [
  { href: '/',                  label: 'Dashboard' },
  { href: '/sectors',           label: 'Sectors' },
  { href: '/ai-journal',        label: 'AI Journal' },
  { href: '/studio',            label: 'Studio' },
  { href: '/admin',             label: 'Admin' },
];

export default function AppNav() {
  const router = useRouter();
  return (
    <nav className="app-nav">
      <Link href="/" className="nav-logo">
        <PumpMark size={20} />
        <span className="logo-word">pump</span>
      </Link>
      {NAV_LINKS.map(({ href, label }) => {
        const isActive = router.pathname === href;
        return (
          <Link key={href} href={href} className={isActive ? 'active' : ''}>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
