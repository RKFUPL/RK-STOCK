'use client';
import { useState } from 'react';
import { API_URL, token } from '@/lib/api';

export function AuthDownload({path,filename,label,className='button button-secondary'}:{path:string;filename:string;label:string;className?:string}){
  const [busy,setBusy]=useState(false); const [error,setError]=useState('');
  async function download(){setBusy(true);setError('');try{const response=await fetch(`${API_URL}${path}`,{headers:{Authorization:`Bearer ${token()}`}});if(!response.ok)throw new Error('Download failed');const blob=await response.blob();const url=URL.createObjectURL(blob);if(path.includes('preview=true')){window.open(url,'_blank','noopener,noreferrer');setTimeout(()=>URL.revokeObjectURL(url),60000)}else{const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}}catch(e){setError(e instanceof Error?e.message:'Download failed')}finally{setBusy(false)}}
  return <span><button type="button" onClick={download} disabled={busy} className={className}>{busy?'Preparing…':label}</button>{error&&<span className="block text-[10px] text-red-700 mt-1">{error}</span>}</span>
}
