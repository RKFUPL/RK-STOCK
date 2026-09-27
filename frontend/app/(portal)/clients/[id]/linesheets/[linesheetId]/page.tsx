'use client';
import { FormEvent, use, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { api, download } from '@/lib/api';
import { PageHeading } from '@/components/page-heading';
import { Empty, ErrorState, Loading } from '@/components/states';

type Document={_id:string;original_name:string;created_at:string;uploaded_by_email?:string};
export default function ClientSheet({params}:{params:Promise<{id:string;linesheetId:string}>}){
  const {id,linesheetId}=use(params); const [items,setItems]=useState<Document[]>([]); const [loading,setLoading]=useState(true); const [busy,setBusy]=useState(false); const [error,setError]=useState('');
  const load=useCallback(async()=>{setLoading(true);setError('');try{setItems((await api<{items:Document[]}>(`/client-linesheets/${linesheetId}/purchase-orders`)).items)}catch(e){setError(e instanceof Error?e.message:'Unable to load purchase orders')}finally{setLoading(false)}},[linesheetId]);
  useEffect(()=>{void load()},[load]);
  async function add(e:FormEvent<HTMLFormElement>){e.preventDefault();setBusy(true);setError('');try{const form=e.currentTarget;await api(`/client-linesheets/${linesheetId}/purchase-orders`,{method:'POST',body:new FormData(form)});form.reset();await load()}catch(e){setError(e instanceof Error?e.message:'Unable to upload purchase order')}finally{setBusy(false)}}
  return <><PageHeading eyebrow="Client linesheet · Purchase orders" title="Purchase order files" description="Multiple PDF purchase orders can be retained against this client linesheet." action={<Link className="button button-secondary" href={`/clients/${id}/linesheets`}>Back to repository</Link>}/><form onSubmit={add} className="card p-5 mb-7 flex flex-col md:flex-row gap-3"><input className="field" type="file" name="file" accept=".pdf,application/pdf" required/><button className="button" disabled={busy}>{busy?'Uploading…':'Upload PO PDF'}</button></form>{error?<ErrorState message={error} retry={load}/>:loading?<Loading/>:items.length===0?<Empty title="No purchase orders" detail="Upload the first PDF above."/>:<div className="table-wrap"><table><thead><tr><th>Filename</th><th>Uploaded</th><th>Uploaded by</th><th></th></tr></thead><tbody>{items.map(doc=><tr key={doc._id}><td>{doc.original_name}</td><td>{new Date(doc.created_at).toLocaleString()}</td><td>{doc.uploaded_by_email||'—'}</td><td><button className="text-xs underline" onClick={()=>void download(`/documents/${doc._id}/download`,doc.original_name)}>Download</button></td></tr>)}</tbody></table></div>}</>;
}
