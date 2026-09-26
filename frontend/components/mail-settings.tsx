'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import { ErrorState, Loading } from '@/components/states';
import { PageHeading } from '@/components/page-heading';
import { SettingsNavigation } from '@/components/settings-navigation';

type MailStatus={configured:boolean;verified:boolean;missing:string[];status:string;verification_error?:string;account_email?:string|null;organization?:string|null;connected_at?:string|null;verified_at?:string|null;last_sent_at?:string|null;scopes:string[];email_settings:{sender_display_name:string;reply_to_email:string;default_signature:string;notifications_enabled:boolean}};
const date=(value?:string|null)=>value?new Date(value).toLocaleString():'Not available';

export function MailSettings(){
  const [status,setStatus]=useState<MailStatus>();const [error,setError]=useState('');const [message,setMessage]=useState('');const [loading,setLoading]=useState(true);const params=useSearchParams();
  const load=()=>{setLoading(true);setError('');api<MailStatus>('/mail/status').then(setStatus).catch(e=>setError(e instanceof Error?e.message:'Unable to load Zoho Mail status')).finally(()=>setLoading(false))};useEffect(()=>{void load()},[]);
  async function connect(){try{const r=await api<{authorization_url:string}>('/mail/connect',{method:'POST'});window.location.assign(r.authorization_url)}catch(e){setError(e instanceof Error?e.message:'Unable to start authorization')}}
  async function test(){try{await api('/mail/test',{method:'POST'});setMessage('Zoho Mail connection verified.');load()}catch(e){setError(e instanceof Error?e.message:'Connection test failed')}}
  async function disconnect(){if(!window.confirm('Disconnect Zoho Mail? Stored OAuth access will be removed.'))return;try{await api('/mail/disconnect',{method:'POST'});setMessage('Zoho Mail disconnected.');load()}catch(e){setError(e instanceof Error?e.message:'Unable to disconnect')}}
  async function save(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);try{await api('/mail/settings',{method:'PATCH',body:JSON.stringify({sender_display_name:f.get('sender_display_name'),reply_to_email:f.get('reply_to_email'),default_signature:f.get('default_signature'),notifications_enabled:f.get('notifications_enabled')==='on'})});setMessage('Email settings saved.');load()}catch(x){setError(x instanceof Error?x.message:'Unable to save settings')}}
  async function sendTest(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);try{await api('/mail/test-email',{method:'POST',body:JSON.stringify({to:f.get('to')})});setMessage('Zoho accepted the test email for delivery.');load()}catch(x){setError(x instanceof Error?x.message:'Test email failed')}}
  return <><SettingsNavigation/><PageHeading eyebrow="Administration → Settings" title="Zoho Mail" description="A separate server-side OAuth connection for verified RK email delivery." action={<div className="flex flex-wrap gap-3"><button className="button" onClick={connect}>{status?.verified?'Reconnect':'Connect'} Zoho Mail</button>{status?.verified&&<button className="button button-secondary" onClick={test}>Test connection</button>}</div>}/>
    {(params.get('message')||message)&&<div className="card alert-success">{params.get('message')||message}</div>}
    {loading?<Loading/>:error?<ErrorState message={error} retry={load}/>:status?<div className="settings-grid">
      <section className="card settings-card"><div className="eyebrow">Connection status</div><h2>{status.verified?'Connected and verified':'Not connected'}</h2><dl><dt>Account</dt><dd>{status.account_email||'Not available'}</dd><dt>Organization</dt><dd>{status.organization||'Not reported'}</dd><dt>Connected date</dt><dd>{date(status.connected_at)}</dd><dt>Last verification</dt><dd>{date(status.verified_at)}</dd></dl>{status.verification_error&&<p className="integration-error">{status.verification_error}</p>}</section>
      <section className="card settings-card"><div className="eyebrow">Permissions</div><h2>Mail API scopes</h2><ul className="detail-list">{status.scopes.map(scope=><li key={scope}>{scope}</li>)}</ul></section>
      <form className="card settings-card lg:col-span-2" onSubmit={save}><div className="eyebrow">Email configuration</div><h2>Sender defaults</h2><div className="form-grid"><label>Default sender account<input className="field" disabled value={status.account_email||''} placeholder="Connect Zoho Mail first"/></label><label>Sender display name<input className="field" name="sender_display_name" defaultValue={status.email_settings.sender_display_name}/></label><label>Reply-to email<input className="field" name="reply_to_email" type="email" defaultValue={status.email_settings.reply_to_email}/></label><label className="md:col-span-2">Default email signature<textarea className="field min-h-32" name="default_signature" defaultValue={status.email_settings.default_signature}/></label><label className="check-row md:col-span-2"><input name="notifications_enabled" type="checkbox" defaultChecked={status.email_settings.notifications_enabled}/> Enable configured email notifications</label></div><button className="button mt-5">Save email settings</button></form>
      <form className="card settings-card" onSubmit={sendTest}><div className="eyebrow">Delivery verification</div><h2>Send test email</h2><p className="secondary-copy">No operational customer messages are sent automatically.</p><input className="field mt-4" name="to" type="email" placeholder="Test recipient" required/><button className="button mt-4" disabled={!status.verified}>Send test email</button><p className="secondary-copy mt-3">Last accepted send: {date(status.last_sent_at)}</p></form>
      <section className="card settings-card danger-card"><div className="eyebrow">Connection control</div><h2>Disconnect Zoho Mail</h2><p className="secondary-copy">This removes the encrypted OAuth token and verified account record.</p><button className="button button-danger" disabled={!status.verified} onClick={disconnect}>Disconnect</button></section>
    </div>:null}
  </>;
}
