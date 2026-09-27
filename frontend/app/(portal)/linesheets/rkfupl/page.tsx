'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { PageHeading } from '@/components/page-heading';
import { Empty, ErrorState, Loading } from '@/components/states';

export default function RKFUPLLinesheets(){
  const [items,setItems]=useState<any[]>([]); const [loading,setLoading]=useState(true); const [error,setError]=useState('');
  useEffect(()=>{api<{items:any[]}>('/linesheets').then(x=>setItems(x.items)).catch(e=>setError(e.message)).finally(()=>setLoading(false))},[]);
  return <><PageHeading eyebrow="Linesheets · RKFUPL" title="RKFUPL linesheets" description="Internal product presentation sheets created by the RK team." action={<Link className="button" href="/linesheets/new">Create linesheet</Link>}/>{error?<ErrorState message={error}/>:loading?<Loading/>:items.length===0?<Empty title="No RKFUPL linesheets" detail="Create an internal draft to begin."/>:<div className="table-wrap"><table><thead><tr><th>Name</th><th>Collection</th><th>Type</th><th>Products</th><th>Status</th><th>Updated</th></tr></thead><tbody>{items.map(x=><tr key={x._id}><td><Link className="font-semibold underline" href={`/linesheets/${x._id}`}>{x.name}</Link></td><td>{x.collection||'—'}</td><td>{x.type||'Not assigned'}</td><td>{x.items?.length||0}</td><td><span className="status">{x.status}</span></td><td>{x.updated_at?new Date(x.updated_at).toLocaleDateString():'—'}</td></tr>)}</tbody></table></div>}</>;
}
