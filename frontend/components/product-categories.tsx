'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '@/lib/api';
import { ErrorState, Loading } from '@/components/states';
import { PageHeading } from '@/components/page-heading';

const MAX_CATEGORY_NAME_LENGTH = 80;

type CategoryResponse = {
  categories: string[];
  usage: Record<string, number>;
  revision: number;
  legacy_issues: Array<{kind:string; index:number|null; value:unknown}>;
};

type CurrentUser = { effective_permissions?: string[] };

function validateCategoryNames(categories: string[]) {
  const cleaned = categories.map((value) => value.trim());
  if (cleaned.some((value) => !value)) return 'Category names cannot be empty.';
  if (cleaned.some((value) => value.length > MAX_CATEGORY_NAME_LENGTH)) return `Category names must be ${MAX_CATEGORY_NAME_LENGTH} characters or fewer.`;
  if (new Set(cleaned.map((value) => value.toLocaleLowerCase())).size !== cleaned.length) return 'Category names must be unique, ignoring capitalization.';
  return '';
}

type Collection = { _id:string; name:string; code?:string; usage?:number };
type CollectionResponse = { items:Collection[]; revision:number; legacy_issues:Array<{kind:string;id?:string;value:unknown}> };

export function CollectionConfiguration() {
  const [data,setData]=useState<CollectionResponse>({items:[],revision:0,legacy_issues:[]}); const [loading,setLoading]=useState(true); const [error,setError]=useState(''); const [message,setMessage]=useState(''); const [busy,setBusy]=useState(false); const [canWrite,setCanWrite]=useState(false); const [draft,setDraft]=useState(''); const [editing,setEditing]=useState<string|null>(null);
  const load=useCallback(async()=>{setLoading(true);setError('');try{const r=await api<CollectionResponse>('/collections');setData({items:r.items||[],revision:r.revision||0,legacy_issues:r.legacy_issues||[]})}catch(e){setError(e instanceof Error?e.message:'Unable to load collections.')}finally{setLoading(false)}},[]);
  useEffect(()=>{void load();api<CurrentUser>('/auth/me').then(u=>setCanWrite((u.effective_permissions||[]).includes('*')||(u.effective_permissions||[]).includes('settings:write'))).catch(()=>setCanWrite(false))},[load]);
  async function save(path:string,options:RequestInit,success:string){setBusy(true);setError('');try{await api(path,options);setMessage(success);setEditing(null);setDraft('');await load()}catch(e){if(e instanceof ApiError&&(e.status===403||e.status===409)){setError(e.message);if(e.status===409)void load()}else setError(e instanceof Error?e.message:'Unable to save collection.')}finally{setBusy(false)}}
  function submit(e:FormEvent){e.preventDefault();const name=draft.trim();if(!name){setError('Enter a collection name.');return}const item=data.items.find(x=>x._id===editing);void save(item?`/collections/${item._id}`:'/collections',{method:item?'PATCH':'POST',body:JSON.stringify({name,revision:data.revision})},item?'Collection renamed.':'Collection added.')}
  function remove(item:Collection){if(!window.confirm(`Remove “${item.name}”? Products and documents are not modified.`))return;void save(`/collections/${item._id}?revision=${data.revision}`,{method:'DELETE'},'Collection removed.')}
  return <section className="mt-8"><div className="flex items-end justify-between gap-3 mb-4"><div><div className="eyebrow">Collection configuration</div><h2 className="font-display text-3xl">Fashion collections</h2><p className="text-sm text-stone-500 mt-1">Collections identify fashion lines such as Aakaar or Hastakala.</p></div>{canWrite&&!editing?<button className="button" type="button" onClick={()=>{setEditing('');setDraft('')}}>Add collection</button>:null}</div>{loading?<Loading/>:error?<ErrorState message={error} retry={()=>void load()}/>:<>{message?<div className="card border-emerald-200 bg-emerald-50 text-emerald-800 mb-4" role="status">{message}</div>:null}{!canWrite?<div className="card border-amber-200 bg-amber-50 text-amber-900 mb-4" role="status">You have read-only access to collection configuration.</div>:null}{data.legacy_issues.length?<div className="card border-amber-200 bg-amber-50 text-amber-900 mb-4" role="alert">Legacy collection data needs cleanup before changes are allowed.</div>:null}{editing!==null?<form className="card p-5 mb-4 flex flex-wrap gap-3" onSubmit={submit}><input className="field flex-1 min-w-60" value={draft} onChange={e=>setDraft(e.target.value)} placeholder="Collection name" disabled={busy} autoFocus/><button className="button" disabled={busy}>{busy?'Saving…':editing?'Rename':'Add'}</button><button className="button button-secondary" type="button" onClick={()=>setEditing(null)} disabled={busy}>Cancel</button></form>:null}{data.items.length?<div className="card p-0 overflow-hidden"><div className="overflow-x-auto"><table className="w-full"><thead><tr><th>Collection</th><th>Code</th><th>Usage</th>{canWrite?<th className="text-right">Actions</th>:null}</tr></thead><tbody>{data.items.map(item=><tr key={item._id}><td className="font-semibold">{item.name}</td><td>{item.code||'—'}</td><td>{item.usage||0} record{item.usage===1?'':'s'}</td>{canWrite?<td className="text-right">{item.usage?<span className="text-xs text-stone-500">In use — changes blocked</span>:<span className="flex justify-end gap-3"><button className="text-xs underline" type="button" onClick={()=>{setEditing(item._id);setDraft(item.name)}}>Rename</button><button className="text-xs underline text-red-700" type="button" onClick={()=>remove(item)}>Remove</button></span>}</td>:null}</tr>)}</tbody></table></div></div>:<div className="card p-10 text-center text-stone-500">No collections configured.</div>}</>}</section>;
}

export function ProductCategories() {
  const [data, setData] = useState<CategoryResponse>({ categories: [], usage: {}, revision: 0, legacy_issues: [] });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [canWrite, setCanWrite] = useState(false);
  const [permissionKnown, setPermissionKnown] = useState(false);
  const [formMode, setFormMode] = useState<'add' | 'rename' | null>(null);
  const [editingCategory, setEditingCategory] = useState('');
  const [draft, setDraft] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const result = await api<CategoryResponse>('/settings/categories');
      setData({ categories: result.categories || [], usage: result.usage || {}, revision: result.revision || 0, legacy_issues: result.legacy_issues || [] });
    } catch (requestError) {
      setLoadError(requestError instanceof Error ? requestError.message : 'Unable to load product categories.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    api<CurrentUser>('/auth/me')
      .then((user) => setCanWrite((user.effective_permissions || []).includes('*') || (user.effective_permissions || []).includes('settings:write')))
      .catch(() => setCanWrite(false))
      .finally(() => setPermissionKnown(true));
  }, [load]);

  const countLabel = useMemo(() => `${data.categories.length} ${data.categories.length === 1 ? 'category' : 'categories'}`, [data.categories.length]);

  function openAdd() {
    setError('');
    setMessage('');
    setEditingCategory('');
    setDraft('');
    setFormMode('add');
  }

  function openRename(category: string) {
    if ((data.usage[category] || 0) > 0) return;
    setError('');
    setMessage('');
    setEditingCategory(category);
    setDraft(category);
    setFormMode('rename');
  }

  function closeForm() {
    if (busy) return;
    setFormMode(null);
    setDraft('');
    setEditingCategory('');
  }

  async function saveCategories(categories: string[], successMessage: string) {
    const validationError = validateCategoryNames(categories);
    if (validationError) {
      setError(validationError);
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const result = await api<CategoryResponse>('/settings/categories', {
        method: 'PUT',
        body: JSON.stringify({ categories: categories.map((value) => value.trim()), revision: data.revision }),
      });
      setData({ categories: result.categories || [], usage: result.usage || {}, revision: result.revision || 0, legacy_issues: result.legacy_issues || [] });
      setMessage(successMessage);
      setFormMode(null);
      setDraft('');
      setEditingCategory('');
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 403) setError('You do not have permission to manage product categories.');
      else if (requestError instanceof ApiError && requestError.status === 409) { setError(requestError.message); void load(); }
      else setError(requestError instanceof Error ? requestError.message : 'Unable to save product categories.');
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = draft.trim();
    if (!name) {
      setError('Enter a category name.');
      return;
    }
    const categories = formMode === 'rename'
      ? data.categories.map((category) => category.toLocaleLowerCase() === editingCategory.toLocaleLowerCase() ? name : category)
      : [...data.categories, name];
    void saveCategories(categories, formMode === 'rename' ? 'Category renamed.' : 'Category added.');
  }

  function remove(category: string) {
    const usage = data.usage[category] || 0;
    if (usage > 0) return;
    if (!window.confirm(`Remove “${category}”? Products are not modified.`)) return;
    void saveCategories(data.categories.filter((value) => value !== category), 'Category removed.');
  }

  if (loading) return <><PageHeading eyebrow="Administration" title="Product categories" description="Categories used by product master records." /><Loading /></>;
  if (loadError) return <><PageHeading eyebrow="Administration" title="Product categories" description="Categories used by product master records." /><ErrorState message={loadError} retry={() => void load()} /></>;

  return <>
    <PageHeading eyebrow="Administration" title="Product categories" description="Manage the category names used by product master records." action={permissionKnown && canWrite ? <button className="button" type="button" onClick={openAdd}>Add category</button> : undefined} />
    {message ? <div className="card border-emerald-200 bg-emerald-50 text-emerald-800 mb-6" role="status">{message}</div> : null}
    {error ? <div className="card border-red-200 bg-red-50 text-red-700 mb-6" role="alert">{error}</div> : null}
    {data.legacy_issues.length ? <div className="card border-amber-200 bg-amber-50 text-amber-900 mb-6" role="alert">Legacy category data needs administrator cleanup before it can be changed ({data.legacy_issues.length} issue{data.legacy_issues.length === 1 ? '' : 's'}).</div> : null}
    {permissionKnown && !canWrite ? <div className="card border-amber-200 bg-amber-50 text-amber-900 mb-6" role="status">You have read-only access to product categories.</div> : null}
    {formMode ? <form className="card p-6 mb-6 max-w-2xl" onSubmit={submit}>
      <div className="eyebrow">{formMode === 'rename' ? 'Rename category' : 'Add category'}</div>
      <label className="block text-sm font-semibold mt-3" htmlFor="category-name">Category name</label>
      <input id="category-name" className="field mt-2" value={draft} maxLength={MAX_CATEGORY_NAME_LENGTH} onChange={(event) => setDraft(event.target.value)} disabled={busy} autoFocus />
      <p className="text-xs text-stone-500 mt-2">Up to {MAX_CATEGORY_NAME_LENGTH} characters. Names are matched without regard to capitalization.</p>
      {formMode === 'rename' ? <p className="text-xs text-stone-500 mt-2">This category is unused, so renaming it will not modify product records.</p> : null}
      <div className="flex gap-3 mt-5"><button className="button" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save category'}</button><button className="button button-secondary" type="button" onClick={closeForm} disabled={busy}>Cancel</button></div>
    </form> : null}
    {data.categories.length === 0 ? <div className="card p-12 text-center"><div className="font-display text-2xl">No product categories configured</div><p className="text-sm text-stone-500 mt-2">Add a category to make it available on product master records.</p>{permissionKnown && canWrite ? <button className="button mt-6" type="button" onClick={openAdd}>Add your first category</button> : null}</div> : <section className="card p-0 overflow-hidden">
      <div className="px-6 py-5 border-b border-stone-200 flex flex-wrap items-center justify-between gap-3"><div><div className="eyebrow">Configured categories</div><p className="text-sm text-stone-500 mt-1">{countLabel}</p></div></div>
      <div className="overflow-x-auto"><table className="w-full"><thead><tr><th>Category</th><th>Product usage</th>{canWrite ? <th className="text-right">Actions</th> : null}</tr></thead><tbody>{data.categories.map((category) => { const usage = data.usage[category] || 0; return <tr key={category}><td className="font-semibold whitespace-nowrap">{category}</td><td>{usage ? `${usage} product${usage === 1 ? '' : 's'}` : 'Unused'}</td>{canWrite ? <td className="text-right"><div className="flex justify-end gap-3">{usage ? <span className="text-xs text-stone-500" title="Rename and removal are blocked while products use this category">In use — removal blocked</span> : <><button className="text-xs underline" type="button" onClick={() => openRename(category)} disabled={busy}>Rename</button><button className="text-xs underline text-red-700" type="button" onClick={() => remove(category)} disabled={busy}>Remove</button></>}</div></td> : null}</tr>; })}</tbody></table></div>
    </section>}
  </>;
}
