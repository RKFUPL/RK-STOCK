'use client';
import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '@/lib/api';
import { Loading } from '@/components/states';
import { PageHeading } from '@/components/page-heading';

type Storefront={status:'not_connected'|'disconnected'|'connected'|'error';configured:boolean;missing?:string[];storefront_url?:string|null;connected_at?:string|null;last_successful_check?:string|null;last_error?:string|null;mapping:{implemented:boolean}};
type CurrentUser={effective_permissions?:string[]};
const date=(value?:string|null)=>value?new Date(value).toLocaleString():'Not available';

export function IntegrationManagement(){
 const [store,setStore]=useState<Storefront>();
 const [storeError,setStoreError]=useState('');
 const [loading,setLoading]=useState(true);
 const [busy,setBusy]=useState<'connect'|'disconnect'|null>(null);
 const [message,setMessage]=useState('');
 const [canWrite,setCanWrite]=useState(false);
 const load=useCallback(async()=>{setLoading(true);setStoreError('');try{setStore(await api<Storefront>('/integrations/storefront/status'))}catch(error){setStore(undefined);setStoreError(error instanceof Error?error.message:'Unable to load storefront integration status.')}finally{setLoading(false)}},[]);
 useEffect(()=>{void load();api<CurrentUser>('/auth/me').then(user=>{const permissions=user.effective_permissions||[];setCanWrite(permissions.includes('*')||permissions.includes('settings:write'))}).catch(()=>setCanWrite(false))},[load]);
 const act=async(action:'connect'|'disconnect')=>{setBusy(action);setMessage('');setStoreError('');try{const next=await api<Storefront>(`/integrations/storefront/${action}`,{method:'POST'});setStore(next);setMessage(action==='connect'?'RK Storefront connection verified.':'RK Storefront connection disconnected.')}catch(error){setStoreError(error instanceof ApiError&&error.status===403?'You can view this connection, but settings:write permission is required to change it.':error instanceof Error?error.message:`Unable to ${action}.`)}finally{setBusy(null)}};
 const connected=store?.status==='connected';
 const title=busy==='connect'?'Connecting…':busy==='disconnect'?'Disconnecting…':connected?'Connected':store?.status==='error'?'Connection failed':'Not connected';
 return <><PageHeading eyebrow="Administration" title="Integration management" description="Manage the authenticated service connection to the RK-WEB storefront."/><div className="settings-grid"><section className="card settings-card"><div className="eyebrow">RK storefront</div>{loading?<Loading/>:<><h2>{title}</h2><dl><dt>Storefront URL</dt><dd>{store?.storefront_url||'Not configured'}</dd><dt>Connected</dt><dd>{date(store?.connected_at)}</dd><dt>Last successful connection check</dt><dd>{date(store?.last_successful_check)}</dd><dt>Catalog and inventory synchronization</dt><dd>Not implemented</dd></dl>{message?<p className="notice notice-success mt-4">{message}</p>:null}{storeError||store?.last_error?<p className="notice notice-error mt-4">{storeError||store?.last_error}</p>:null}{!store?.configured?<p className="notice notice-error mt-4">Server-side configuration is incomplete. Set {store?.missing?.join(', ')||'the required integration environment variables'} in the Stock backend environment, then reload this page. Secret values are never shown here.</p>:null}<div className="flex gap-3 mt-5"><button className="button" type="button" disabled={!canWrite||!store?.configured||connected||busy!==null} onClick={()=>void act('connect')}>{busy==='connect'?'Connecting…':'Connect'}</button><button className="button button-danger" type="button" disabled={!canWrite||!connected||busy!==null} onClick={()=>void act('disconnect')}>{busy==='disconnect'?'Disconnecting…':'Disconnect'}</button>{store?.status==='error'?<button className="button button-secondary" type="button" disabled={busy!==null} onClick={()=>void load()}>Retry check</button>:null}</div>{!canWrite?<p className="secondary-copy mt-3">Read-only access. The settings:write permission is required to connect or disconnect.</p>:null}<p className="secondary-copy mt-3">Connection confirms authenticated service access only. It does not synchronize products, collections, inventory, orders, or payments.</p></>}</section></div></>;
}
