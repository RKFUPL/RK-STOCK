'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { PageHeading } from '@/components/page-heading';

type Profile = { name?: string; username?: string; email?: string; role?: string; active?: boolean; last_login_at?: string };

export default function AccountPage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { api<Profile>('/auth/me').then(setProfile).catch((reason) => setError(reason instanceof Error ? reason.message : 'Unable to load your profile.')); }, []);
  return <>
    <PageHeading eyebrow="Account" title="My profile" description="Your local RK-STOCK identity and account status." action={<Link className="button button-secondary" href="/change-password">Change password</Link>} />
    {error && <div className="card border-red-200 bg-red-50 text-red-800" role="alert">{error}</div>}
    {profile && <div className="card p-6 max-w-2xl grid gap-5 md:grid-cols-2">
      <div><div className="eyebrow">Name</div><div className="text-lg font-semibold mt-1">{profile.name || '—'}</div></div>
      <div><div className="eyebrow">Role</div><div className="text-lg font-semibold mt-1 capitalize">{profile.role || '—'}</div></div>
      <div><div className="eyebrow">Username</div><div className="mt-1">{profile.username ? `@${profile.username}` : '—'}</div></div>
      <div><div className="eyebrow">Email</div><div className="mt-1">{profile.email || '—'}</div></div>
      <div><div className="eyebrow">Status</div><div className="mt-1"><span className="status">{profile.active === false ? 'Inactive' : 'Active'}</span></div></div>
      <div><div className="eyebrow">Last login</div><div className="mt-1">{profile.last_login_at ? new Date(profile.last_login_at).toLocaleString() : 'Not available'}</div></div>
    </div>}
  </>;
}
