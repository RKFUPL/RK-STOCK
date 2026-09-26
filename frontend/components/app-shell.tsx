'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { Bars3Icon, MagnifyingGlassIcon, XMarkIcon } from '@heroicons/react/24/outline';
import { api } from '@/lib/api';

const groups = [
  ['Dashboard',[['Overview','/']]],
  ['Clients',[['MDS clients','/clients/mds'],['Direct clients','/clients/direct']]],
  ['Linesheets',[['Linesheet dashboard','/linesheets/dashboard'],['All linesheets','/linesheets'],['Create linesheet','/linesheets/new'],['Import linesheet','/linesheets/import'],['Templates','/linesheets/templates']]],
  ['Sales',[['All orders','/sales/orders'],['MDS outright','/sales/mds-outright'],['MDS consignment','/sales/mds-consignment'],['Direct clients','/sales/direct-clients'],['Pending production','/sales/pending-production'],['PO lookup','/sales/po-lookup'],['Ready to dispatch','/sales/ready-to-dispatch'],['Executed orders','/sales/executed-orders']]],
  ['Inventory',[['Stock dashboard','/inventory'],['Product images','/inventory/product-images'],['Stock ledger','/inventory/ledger'],['Adjustments','/inventory/adjust'],['Consignment stock','/inventory/consignment'],['Low stock','/inventory/low-stock']]],
  ['Production',[['Production dashboard','/production'],['Production queue','/production/queue'],['Stage tracking','/production/stage-tracking']]],
  ['Documents',[['Purchase orders','/documents/purchase-orders'],['Generated linesheets','/documents/generated-linesheets'],['Exported reports','/reports']]],
  ['Administration',[['Users & roles','/workspace/users'],['WorkDrive settings','/workspace/settings'],['Zoho Mail settings','/workspace/mail'],['Categories','/workspace/categories']]],
] as const;

export function AppShell({children}:{children:React.ReactNode}) {
  const [open,setOpen]=useState(false); const [search,setSearch]=useState(''); const path=usePathname(); const router=useRouter();
  useEffect(()=>{ if(!sessionStorage.getItem('rk_token')) router.replace('/login'); else api('/auth/me').catch(()=>router.replace('/login')); },[router]);
  const sidebar=<><div className="min-h-28 px-6 py-5 flex items-center border-b border-white/10"><div><div className="font-display text-2xl tracking-wide">RK</div><div className="text-[18px] leading-tight uppercase tracking-[.18em] text-[#c9aa78]">Fashion Operations</div></div></div><nav className="p-3 overflow-y-auto h-[calc(100vh-7rem)]">{groups.map(([group,items])=><div key={group} className="mb-5"><div className="px-3 mb-2 text-[18px] leading-tight tracking-[.14em] uppercase text-white/35">{group}</div>{items.map(([label,href])=>{const active=path===href;return <Link aria-current={active?'page':undefined} onClick={()=>setOpen(false)} key={href} href={href} className={`block rounded-lg px-3 py-3 text-[24px] leading-tight transition-colors ${active?'bg-white/10 text-white':'bg-transparent text-white/60 hover:bg-white/5 hover:text-white'}`}>{label}</Link>})}</div>)}</nav></>;
  function doSearch(e:React.FormEvent){e.preventDefault(); if(search.trim()) router.push(`/sales/po-lookup?q=${encodeURIComponent(search.trim())}`)}
  return <div className="min-h-screen"><aside className="desktop-only fixed inset-y-0 left-0 w-80 bg-charcoal text-white z-30">{sidebar}</aside>{open&&<div className="fixed inset-0 z-40 md:hidden"><button aria-label="Close menu" className="absolute inset-0 bg-black/50" onClick={()=>setOpen(false)}/><aside className="relative w-[90vw] max-w-md bg-charcoal text-white h-full"><button onClick={()=>setOpen(false)} className="absolute top-6 right-5"><XMarkIcon className="w-8"/></button>{sidebar}</aside></div>}<div className="md:ml-80"><header className="min-h-24 sticky top-0 z-20 border-b border-stone-200/80 bg-ivory/90 backdrop-blur flex items-center px-5 md:px-8 py-3 gap-4"><button className="md:hidden" onClick={()=>setOpen(true)} aria-label="Open menu"><Bars3Icon className="w-8"/></button><form onSubmit={doSearch} className="relative flex-1 max-w-3xl"><MagnifyingGlassIcon className="absolute w-6 left-4 top-1/2 -translate-y-1/2 text-stone-400"/><input value={search} onChange={e=>setSearch(e.target.value)} className="field !pl-12" placeholder="Search PO, client, SKU or product"/></form><button className="text-xs text-stone-500" onClick={()=>{sessionStorage.clear();router.replace('/login')}}>Sign out</button></header><main className="p-5 md:p-8 lg:p-10 max-w-[1800px] mx-auto">{children}</main></div></div>
}
