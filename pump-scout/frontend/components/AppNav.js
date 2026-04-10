/**
 * AppNav — Shared top navigation bar for all Pump Scout pages.
 * Unified premium dark-mode navigation — part of the design system.
 */
import Link from 'next/link';
import { useRouter } from 'next/router';

const NAV_LINKS = [
  { href: '/',             label: 'Scanner' },
  { href: '/ribbon',       label: 'Ribbon' },
  { href: '/ignition',     label: 'Ignition' },
  { href: '/sectors',      label: 'Sectors' },
  { href: '/journal',      label: 'Journal' },
  { href: '/ai-portfolio', label: 'AI Portfolio' },
  { href: '/macro-events', label: 'Macro' },
  { href: '/ai-analyst',   label: 'AI Analyst' },
  { href: '/ai-review',    label: 'AI Review' },
  { href: '/ai-insights',  label: 'AI Insights' },
  { href: '/admin',          label: 'Admin' },
  { href: '/design-system',  label: 'Design System' },
];

export default function AppNav() {
  const router = useRouter();

  return (
    <nav className="app-nav">
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
