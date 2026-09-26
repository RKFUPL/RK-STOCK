'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const items = [
  ['General', '/workspace/general'],
  ['Zoho WorkDrive', '/workspace/settings'],
  ['Zoho Mail', '/workspace/mail'],
  ['Email Notifications', '/workspace/email-notifications'],
  ['Security', '/workspace/security'],
] as const;

export function SettingsNavigation() {
  const pathname = usePathname();
  return <nav aria-label="Settings sections" className="settings-nav card p-2 mb-8">
    {items.map(([label, href]) => <Link key={href} href={href} aria-current={pathname === href ? 'page' : undefined} className={pathname === href ? 'active' : ''}>{label}</Link>)}
  </nav>;
}
