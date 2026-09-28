'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import { ErrorState, Loading } from '@/components/states';
import { PageHeading } from '@/components/page-heading';
import { SettingsNavigation } from '@/components/settings-navigation';

type Status = { configured:boolean; verified:boolean; root_folder_configured:boolean; root_folder_name?:string|null; connected_account_email?:string|null; connected_at?:string|null; verified_at?:string|null; missing:string[]; status:string; verification_error?:string; storage_structure:Array<{name:string;type:string;verified:boolean}>; synchronization:{counts:Record<string,number>;last_successful_sync?:string|null} };
const date = (value?:string|null) => value ? new Date(value).toLocaleString() : 'Not available';

export function WorkDriveSettings() {
  const [status,setStatus]=useState<Status>(); const [error,setError]=useState(''); const [loading,setLoading]=useState(true); const params=useSearchParams();
  const load=()=>{setLoading(true);setError('');api<Status>('/workdrive/status').then(setStatus).catch(e=>setError(e instanceof Error?e.message:'Unable to load WorkDrive status')).finally(()=>setLoading(false))};
  useEffect(()=>{void load()},[]);
  async function connect(){try{const result=await api<{authorization_url:string}>('/workdrive/connect',{method:'POST'});window.location.assign(result.authorization_url)}catch(e){setError(e instanceof Error?e.message:'Unable to start authorization')}}
  async function test(){try{await api('/workdrive/test',{method:'POST'});load()}catch(e){setError(e instanceof Error?e.message:'Connection test failed')}}
  async function disconnect(){if(!window.confirm('Disconnect Zoho WorkDrive? Stored OAuth access will be removed.'))return;try{await api('/workdrive/disconnect',{method:'POST'});load()}catch(e){setError(e instanceof Error?e.message:'Unable to disconnect WorkDrive')}}
  return <><SettingsNavigation/><PageHeading eyebrow="Administration → Settings" title="Zoho WorkDrive" description="Secure document storage and synchronization for RK operational records." action={<div className="flex flex-wrap gap-3"><button className="button" onClick={connect}>{status?.verified?'Reconnect':'Connect'} WorkDrive</button>{status?.verified&&<button className="button button-secondary" onClick={test}>Test connection</button>}</div>}/>
    {params.get('message')&&<div className="card alert-error">{params.get('message')}</div>}
    {loading?<Loading/>:error?<ErrorState message={error} retry={load}/>:status?<div className="settings-grid">
      <section className="card settings-card"><div className="eyebrow">Connection status</div><h2>{status.verified?'Connected and verified':'Not connected'}</h2><dl><dt>Zoho account</dt><dd>{status.connected_account_email||'Not reported by WorkDrive'}</dd><dt>Connected date</dt><dd>{date(status.connected_at)}</dd><dt>Last verification</dt><dd>{date(status.verified_at)}</dd></dl>{!status.configured&&<p className="integration-error">Configuration incomplete: {status.missing.length ? status.missing.join(', ') : 'backend configuration is incomplete'}.</p>}{status.verification_error&&<p className="integration-error">{status.verification_error}</p>}</section>
      <section className="card settings-card"><div className="eyebrow">Storage structure</div><h2>{status.root_folder_name||'Root folder not configured'}</h2>{status.storage_structure.length?<ul className="detail-list">{status.storage_structure.map(item=><li key={item.name}><span>{item.name}</span><span className="status">{item.verified?'Verified':'Pending'}</span></li>)}</ul>:<p className="secondary-copy">No verified storage structure is available.</p>}</section>
      <section className="card settings-card"><div className="eyebrow">Synchronization</div><h2>Document sync status</h2><ul className="detail-list">{Object.entries(status.synchronization.counts).map(([key,value])=><li key={key}><span>{key.replaceAll('_',' ')}</span><strong>{value}</strong></li>)}</ul>{Object.keys(status.synchronization.counts).length===0&&<p className="secondary-copy">No document synchronization attempts recorded.</p>}</section>
      <section className="card settings-card danger-card"><div className="eyebrow">Connection control</div><h2>Disconnect WorkDrive</h2><p className="secondary-copy">This removes the stored OAuth connection. It does not delete remote files.</p><button className="button button-danger" disabled={!status.verified} onClick={disconnect}>Disconnect</button></section>
    </div>:null}
  </>;
}
