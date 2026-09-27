'use client';
import { use, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { ClientForm } from '@/components/client-form';
export default function Page({params}:{params:Promise<{id:string}>}){const {id}=use(params);const [client,setClient]=useState<any>();const [error,setError]=useState('');useEffect(()=>{api<any>(`/clients/${id}`).then(x=>setClient(x.client)).catch(e=>setError(e.message))},[id]);if(error)return <p className="text-sm text-red-700">{error}</p>;if(!client)return <p className="text-sm text-stone-500">Loading client…</p>;return <ClientForm category={client.category} initial={client} edit/>}
