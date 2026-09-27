'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { api } from '@/lib/api';
import { ErrorState, Loading } from '@/components/states';
import { PageHeading } from '@/components/page-heading';

type Worksheet={name:string;rows:unknown[][];freeze_panes:string;column_widths:Record<string,number>};
type Preview={linesheet:{name?:string;linesheet_number:string};worksheets:Worksheet[]};

export default function ExcelPreview(){
  const {id}=useParams<{id:string}>(); const [data,setData]=useState<Preview>(); const [active,setActive]=useState(0); const [error,setError]=useState('');
  useEffect(()=>{api<Preview>(`/linesheets/${id}/preview.xlsx`).then(setData).catch(e=>setError(e.message))},[id]);
  if(error)return <ErrorState message={error}/>; if(!data)return <Loading/>;
  const worksheet=data.worksheets[active];
  return <><PageHeading eyebrow="Excel workbook preview" title={data.linesheet.name||data.linesheet.linesheet_number} description="Read-only browser preview of the generated workbook." action={<Link className="button button-secondary" href={`/linesheets/${id}`}>Close preview</Link>}/><div className="card p-0 overflow-hidden"><div className="flex gap-1 overflow-x-auto border-b border-stone-200 bg-stone-100 px-3 pt-3">{data.worksheets.map((item,index)=><button key={item.name} className={`px-4 py-2 text-sm border rounded-t ${index===active?'bg-white border-b-white font-semibold':'bg-stone-50 text-stone-600'}`} onClick={()=>setActive(index)}>{item.name}</button>)}</div><div className="max-h-[72vh] overflow-auto"><table className="min-w-max border-collapse"><tbody>{worksheet?.rows.map((row,rowIndex)=><tr key={rowIndex}>{row.map((cell,columnIndex)=><td key={columnIndex} className={`${rowIndex===0?'sticky top-0 z-10 bg-[#2a2622] text-white font-semibold':'bg-white'} border border-stone-200 px-3 py-2 align-top whitespace-pre-wrap`} style={{minWidth:`${Math.min(Math.max(Object.values(worksheet.column_widths)[columnIndex]||12,8),40)}ch`}}>{cell==null?'':String(cell)}</td>)}</tr>)}</tbody></table></div></div></>;
}
