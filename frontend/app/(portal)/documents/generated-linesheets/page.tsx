'use client';
import { OperationalListPage } from '@/components/operational-list-page';
const columns=[{key:'linesheet_number',label:'Linesheet'},{key:'client_name',label:'Client'},{key:'type',label:'Type',format:(v:unknown)=>String(v||'').replaceAll('_',' ')},{key:'collection',label:'Collection'},{key:'total_quantity',label:'Quantity'},{key:'status',label:'Status',format:(v:unknown)=><span className="status">{String(v||'').replaceAll('_',' ')}</span>}];
export default function Page(){return <OperationalListPage eyebrow="Documents" title="Generated linesheets" description="Saved client linesheets and their current sharing or conversion status." endpoint="/linesheets" columns={columns} emptyTitle="No generated linesheets" relatedHref="/linesheets/new" relatedLabel="Create linesheet"/>}
