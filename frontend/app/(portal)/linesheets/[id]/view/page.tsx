'use client';
import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { api, authenticatedBlobUrl } from '@/lib/api';
import { PageHeading } from '@/components/page-heading';
import { ErrorState, Loading } from '@/components/states';
import { AuthDownload } from '@/components/auth-download';

function ProductImage({linesheetId,image}:{linesheetId:string;image:any}){
  const [url,setUrl]=useState('');
  useEffect(()=>{if(!image?.id)return;let active=true;let created='';authenticatedBlobUrl(`/linesheets/${linesheetId}/images/${image.id}`).then(value=>{created=value;if(active)setUrl(value)}).catch(()=>{});return()=>{active=false;if(created)URL.revokeObjectURL(created)}},[linesheetId,image?.id]);
  return url?<a href={url} target="_blank" rel="noreferrer"><img src={url} alt={image?.filename||'Product'} className="w-16 h-20 object-contain rounded border border-stone-200 bg-white"/></a>:<div className="w-16 h-20 grid place-items-center rounded border border-stone-200 bg-stone-50 text-xs text-stone-400">No image</div>;
}

export default function Page(){
  const {id}=useParams<{id:string}>(); const [sheet,setSheet]=useState<any>(); const [error,setError]=useState(''); const [query,setQuery]=useState('');
  useEffect(()=>{api<any>(`/linesheets/${id}`).then(x=>setSheet(x.linesheet)).catch(e=>setError(e.message))},[id]);
  const rows=useMemo(()=>{const items=sheet?.items||[];const q=query.trim().toLowerCase();return q?items.filter((x:any)=>[x.product_code,x.vendor_code,x.description,x.product_name,x.color,x.linesheet_sku,x.sku,x.category].some(value=>String(value||'').toLowerCase().includes(q))):items},[sheet,query]);
  if(error)return <ErrorState message={error}/>; if(!sheet)return <Loading/>;
  return <><PageHeading eyebrow="Read-only linesheet viewer" title={sheet.name||sheet.linesheet_number} description={`${sheet.linesheet_number} · ${sheet.client_name||'Internal'} · ${sheet.collection||'No collection'} · ${sheet.type||'No order type'}`} action={<Link className="button button-secondary" href={`/linesheets/${id}`}>Back to linesheet</Link>}/><div className="flex flex-wrap items-center gap-2 mb-5"><input className="field max-w-sm" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search products, colours or SKU"/><AuthDownload path={`/linesheets/${id}/export.xlsx`} filename={`${sheet.linesheet_number}.xlsx`} label="Export Excel"/><AuthDownload path={`/linesheets/${id}/export.pdf`} filename={`${sheet.linesheet_number}.pdf`} label="Export PDF"/><span className="text-sm text-stone-500">{rows.length} of {(sheet.items||[]).length} rows</span></div><div className="table-wrap max-h-[72vh] overflow-auto"><table className="min-w-[1380px]"><thead className="sticky top-0 z-10 bg-stone-100"><tr><th className="sticky left-0 z-20 bg-stone-100">#</th><th>Image</th><th>Product Code</th><th>Description</th><th>Colour</th><th>Category</th><th>Set Of</th><th>Sizes / Quantities</th><th>MRP</th><th>Linesheet SKU</th><th>Remark</th><th>Delivery Date</th></tr></thead><tbody>{rows.map((x:any,i:number)=><tr key={`${x.linesheet_sku||x.sku}-${i}`} className="align-top"><td className="sticky left-0 bg-white font-mono text-xs">{i+1}</td><td><ProductImage linesheetId={id} image={x.images?.[0]}/></td><td className="font-semibold">{x.product_code||x.vendor_code||'—'}</td><td className="min-w-64 whitespace-normal">{x.description||x.product_name||'—'}</td><td>{x.color||'—'}</td><td>{x.category||'—'}</td><td>{x.set_of||x.component_count||1}</td><td>{Object.entries(x.size_quantities||{}).length?Object.entries(x.size_quantities).map(([size,qty])=>`${size}: ${qty}`).join(', '):(x.sizes||[]).join(', ')||'—'}</td><td>{x.mrp||x.unit_price||'—'}</td><td className="font-mono text-xs">{x.linesheet_sku||x.sku||'—'}</td><td className="whitespace-normal min-w-48">{x.remark||x.references?.join(', ')||'—'}</td><td>{x.po_delivery_date||'—'}</td></tr>)}{!rows.length&&<tr><td colSpan={12} className="text-center py-12 text-stone-500">No matching product rows.</td></tr>}</tbody></table></div></>;
}
