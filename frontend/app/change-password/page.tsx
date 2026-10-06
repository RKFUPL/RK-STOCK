'use client';

import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';

export default function ChangePasswordPage() {
  const router = useRouter();
  const [currentPassword, setCurrentPassword] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('');
    if (password.length < 8) return setError('Password must be at least 8 characters.');
    if (password !== confirmPassword) return setError('Password confirmation does not match.');
    setBusy(true);
    try {
      await api('/auth/password/change', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, password, confirm_password: confirmPassword }) });
      router.replace('/');
    } catch (value) { setError(value instanceof Error ? value.message : 'Unable to change password.'); }
    finally { setBusy(false); }
  }

  return <main className="min-h-screen bg-ivory grid place-items-center p-7"><form onSubmit={submit} className="card w-full max-w-lg p-8 md:p-11"><div className="eyebrow">Account security</div><h1 className="font-display text-4xl mt-3">Change your RK Operations password</h1><p className="secondary-copy mt-3 mb-8">Set a private Stock password before continuing to operational tools.</p><label className="block text-xs font-semibold mb-2">Current password</label><input className="field mb-5" type="password" autoComplete="current-password" required value={currentPassword} onChange={event=>setCurrentPassword(event.target.value)}/><label className="block text-xs font-semibold mb-2">New password</label><input className="field mb-2" type="password" autoComplete="new-password" minLength={8} required value={password} onChange={event=>setPassword(event.target.value)}/><p className="text-xs text-stone-500 mb-5">Use at least 8 characters and do not reuse the temporary password.</p><label className="block text-xs font-semibold mb-2">Confirm new password</label><input className="field mb-4" type="password" autoComplete="new-password" minLength={8} required value={confirmPassword} onChange={event=>setConfirmPassword(event.target.value)}/>{error&&<p role="alert" className="text-sm text-red-700 my-3">{error}</p>}<button className="button w-full mt-3" disabled={busy}>{busy?'Saving…':'Change password'}</button></form></main>;
}
