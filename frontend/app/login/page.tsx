'use client';
import { FormEvent, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter(); const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setError(''); const form=new FormData(event.currentTarget); try { const result=await api<{token?:string; shared?:boolean}>('/auth/login',{method:'POST',body:JSON.stringify({identifier:form.get('identifier'),password:form.get('password')})}); if (result.token) sessionStorage.setItem('rk_token',result.token); else sessionStorage.removeItem('rk_token'); router.replace('/'); } catch(e) { setError(e instanceof Error?e.message:'Unable to sign in. Please try again.'); } finally {setBusy(false)} }
  return <main className="min-h-screen grid lg:grid-cols-[1.1fr_.9fr] bg-ivory">
    <section className="hidden lg:flex relative overflow-hidden bg-charcoal text-white p-16 flex-col justify-between"><div className="absolute inset-0 opacity-20" style={{backgroundImage:'radial-gradient(circle at 30% 10%, #d7b57d, transparent 35%), radial-gradient(circle at 80% 75%, #a47e45, transparent 30%)'}}/><div className="relative"><div className="eyebrow !text-[#d7b57d]">Rashi Kapoor Fashion</div><h1 className="font-display text-5xl leading-[1.08] mt-5 max-w-2xl">Precision behind every collection.</h1></div><p className="relative max-w-md text-white/60 leading-relaxed">Linesheets, purchase orders, production, stock and dispatch — one private operating system for the RK team.</p></section>
    <section className="flex items-center justify-center p-7"><form onSubmit={submit} className="w-full max-w-md card p-8 md:p-11"><div className="eyebrow">Internal portal</div><h2 className="font-display text-4xl mt-3 mb-2">Welcome back</h2><p className="text-sm text-stone-500 mb-8">Sign in with your RK operations account.</p><label className="block text-xs font-semibold mb-2">Email or username</label><input className="field mb-5" name="identifier" type="text" required autoComplete="username"/><label className="block text-xs font-semibold mb-2">Password</label><input className="field mb-3" name="password" type="password" required autoComplete="current-password"/>{error&&<p role="alert" className="text-sm text-red-700 my-3">{error}</p>}<button disabled={busy} className="button w-full mt-4">{busy?'Signing in…':'Sign in securely'}</button></form></section>
  </main>
}
