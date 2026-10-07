'use client';

import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, api, authenticatedBlobUrl } from '@/lib/api';
import { PageHeading } from '@/components/page-heading';
import { Empty, ErrorState, Loading } from '@/components/states';
import { ProductVariantManager } from '@/components/product-variant-manager';
import { ProductInventoryManager } from '@/components/product-inventory-manager';
import { ProductLifecycleActions } from '@/components/product-lifecycle-actions';
import { ProductSyncStatus } from '@/components/product-sync-status';

type Product = Record<string, any> & { _id: string; sku?: string; name?: string; images: any[] };
type Tab = 'overview' | 'media' | 'details' | 'variants' | 'inventory' | 'collections' | 'history';

const text = (value: unknown, fallback = 'Not available') => value === undefined || value === null || value === '' ? fallback : String(value);
const statusOf = (product: Product) => product.status || (product.active === false ? 'archived' : 'active');
const colorsOf = (product: Product) => product.colors || product.colours || (product.color ? [product.color] : []);
const collectionNamesOf = (product: Product) => product.collection_names?.length ? product.collection_names : product.collections?.map((item: any) => item.name).filter(Boolean) || (product.collection || product.collection_name ? [product.collection || product.collection_name] : []);
const collectionOf = (product: Product) => collectionNamesOf(product).join(', ') || product.collection_code;
const imageUrl = (image: any) => typeof image === 'string' ? image : image?.url || image?.permalink || image?.src || '';
const mediaStatus = (product: Product) => product.images?.length ? (product.images.some((image: any) => image.is_main || image.is_primary || image.view === 'main') ? 'Complete' : 'Missing primary') : 'Missing primary';
const inventoryStatus = (product: Product) => {
  if (typeof product.available === 'number') return product.available > 0 ? 'In stock' : 'Out of stock';
  if (typeof product.stock === 'number') return product.stock > 0 ? 'In stock' : 'Out of stock';
  return 'Not available';
};
const draftFor = (product: Product) => ({ name: product.name || '', sku: product.sku || '', product_code: product.product_code || '', category: product.category || '', description: product.description || '', selling_price: product.selling_price ?? product.price ?? '', colors: colorsOf(product).join(', '), active: product.active !== false, collection_ids: (product.collection_ids || []).map(String) });

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="card p-4"><div className="text-[11px] uppercase tracking-[.16em] text-stone-500">{label}</div><div className="font-display text-3xl mt-2 text-charcoal">{value}</div></div>;
}

function ProductPlaceholder({ large = false }: { large?: boolean }) {
  return <div className={`${large ? 'h-56' : 'h-14 w-14'} bg-gradient-to-br from-[#eee6d8] to-[#d9cbb5] flex items-center justify-center text-[#856c4a] ${large ? 'text-sm' : 'text-[10px]'} uppercase tracking-[.14em]`}>RK</div>;
}

const workDrivePreviewCache = new Map<string, string>();
const workDrivePreviewRequests = new Map<string, Promise<string>>();

function forgetWorkDrivePreview(productId: string, mediaId: string) {
  workDrivePreviewCache.delete(`${productId}:${mediaId}`);
}

function cachedWorkDrivePreview(productId: string, mediaId: string) {
  const key = `${productId}:${mediaId}`;
  const cached = workDrivePreviewCache.get(key);
  if (cached) return Promise.resolve(cached);
  const pending = workDrivePreviewRequests.get(key);
  if (pending) return pending;
  const request = authenticatedBlobUrl(`/products/${productId}/media/${mediaId}/preview/image`)
    .then(url => { workDrivePreviewCache.set(key, url); workDrivePreviewRequests.delete(key); return url; })
    .catch(error => { workDrivePreviewRequests.delete(key); throw error; });
  workDrivePreviewRequests.set(key, request);
  return request;
}

function WorkDrivePreview({ image, productId, large, alt }: { image: any; productId: string; large: boolean; alt: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [previewUrl, setPreviewUrl] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    if (!image.id || image.type !== 'image') return () => { active = false; };
    setFailed(false);
    const load = () => cachedWorkDrivePreview(productId, image.id).then(url => { if (active) setPreviewUrl(url); }).catch(() => { if (active) setFailed(true); });
    const element = containerRef.current;
    if (!element || typeof IntersectionObserver === 'undefined') { void load(); return () => { active = false; }; }
    const observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); void load(); } }, { rootMargin: '240px' });
    observer.observe(element);
    return () => { active = false; observer.disconnect(); };
  }, [image.id, productId, image.type]);
  if (previewUrl && !failed) return <img src={previewUrl} alt={alt} loading="lazy" onError={() => { forgetWorkDrivePreview(productId, image.id); setFailed(true); }} className={`${large ? 'h-56 w-full' : 'h-14 w-14'} object-cover bg-[#eee6d8]`} />;
  return <div ref={containerRef} className={`${large ? 'h-56' : 'h-14 w-14'} bg-[#eee6d8] flex flex-col items-center justify-center text-center text-[#856c4a] px-2`}><span className="text-[10px] uppercase tracking-[.14em]">WorkDrive image</span><span className="text-[10px] mt-1">{failed ? 'Preview unavailable' : 'Loading preview…'}</span></div>;
}

function ProductImage({ image, productId, large = false, alt }: { image: any; productId?: string; large?: boolean; alt: string }) {
  if (image?.provider === 'zoho_workdrive') {
    const resolvedProductId = productId || image.product_id;
    const permalink = typeof image.permalink === 'string' ? image.permalink : '';
    const isEmbed = image.type === 'embed' && /^https:\/\/workdrive\.zohoexternal\.in\//i.test(permalink);
    if (isEmbed) return <iframe title={alt} src={permalink} loading="lazy" className={`${large ? 'h-56 w-full' : 'h-14 w-14'} border-0 bg-[#eee6d8]`} />;
    return resolvedProductId ? <WorkDrivePreview image={image} productId={resolvedProductId} large={large} alt={alt} /> : <ProductPlaceholder large={large} />;
  }
  const url = imageUrl(image);
  return url ? <img src={url} alt={alt} loading="lazy" className={`${large ? 'h-56 w-full' : 'h-14 w-14'} object-cover bg-[#eee6d8]`} /> : <ProductPlaceholder large={large} />;
}

type WorkDriveRow = { id: number; permalink: string; altText: string; description: string; primary: boolean; error?: string };

function extractWorkDriveLinks(value: string) {
  const matches = value.match(/https:\/\/(?:workdrive\.zoho\.in|workdrive\.zohoexternal\.in)\/file\/[A-Za-z0-9_-]+/gi) || [];
  const seen = new Set<string>();
  return matches.map(match => { const url = new URL(match); return `https://${url.hostname.toLowerCase()}${url.pathname}`; }).filter(url => !seen.has(url) && Boolean(seen.add(url)));
}

function ExternalMediaPanel({ product, canWrite, onSaved }: { product: Product; canWrite: boolean; onSaved: () => Promise<void> }) {
  const [rows, setRows] = useState<WorkDriveRow[]>([{ id: 1, permalink: '', altText: '', description: '', primary: false }]);
  const [pasteBlock, setPasteBlock] = useState('');
  const [pastePrimary, setPastePrimary] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const detectedLinks = useMemo(() => extractWorkDriveLinks(pasteBlock), [pasteBlock]);
  function updateRow(id: number, changes: Partial<WorkDriveRow>) { setRows(current => current.map(row => row.id === id ? { ...row, ...changes, error: undefined } : row)); }
  function addRow() { setRows(current => [...current, { id: Date.now() + current.length, permalink: '', altText: '', description: '', primary: false }]); }
  function removeRow(id: number) { setRows(current => current.length === 1 ? current : current.filter(row => row.id !== id)); }
  function validPermalink(value: string) {
    try { const url = new URL(value.trim()); return url.protocol === 'https:' && (url.hostname.toLowerCase() === 'workdrive.zoho.in' || url.hostname.toLowerCase() === 'workdrive.zohoexternal.in') && !url.username && !url.password && Boolean(url.pathname); }
    catch { return false; }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const pastedRows: WorkDriveRow[] = detectedLinks.map((permalink, index) => ({ id: -(index + 1), permalink, altText: '', description: '', primary: pastePrimary && index === 0 }));
    const seen = new Set<string>();
    const entered = [...pastedRows, ...rows.filter(row => row.permalink.trim())].filter(row => { const key = row.permalink.trim(); if (seen.has(key)) return false; seen.add(key); return true; });
    const invalid = entered.filter(row => !validPermalink(row.permalink));
    const pastedCandidates = pasteBlock.match(/(?:https?|javascript|data):[^\s]+/gi) || [];
    const rejectedPaste = pastedCandidates.some(candidate => !extractWorkDriveLinks(candidate).length);
    if (!entered.length) { setError('Add at least one WorkDrive permalink.'); setBusy(false); return; }
    if (invalid.length || rejectedPaste) { setRows(current => current.map(row => invalid.some(item => item.id === row.id) ? { ...row, error: 'Use an approved HTTPS WorkDrive file permalink.' } : row)); setError('One or more pasted links are not approved HTTPS WorkDrive file permalinks.'); setBusy(false); return; }
    if (entered.filter(row => row.primary).length > 1) { setError('Select at most one new primary media item.'); setBusy(false); return; }
    const failures: number[] = []; const failedPasted: string[] = []; let position = product.images?.length || 0;
    for (const row of entered) {
      try { await api(`/products/${product._id}/media`, { method: 'POST', body: JSON.stringify({ provider: 'zoho_workdrive', type: 'image', permalink: row.permalink.trim(), source: 'rk-stock', position, is_primary: row.primary, alt_text: row.altText, description: row.description }) }); position += 1; }
      catch (value) { failures.push(row.id); if (row.id < 0) failedPasted.push(row.permalink); else setRows(current => current.map(item => item.id === row.id ? { ...item, error: value instanceof Error ? value.message : 'Unable to add this WorkDrive link.' } : item)); }
    }
    setPasteBlock(failedPasted.join('\n')); setPastePrimary(false);
    setRows(current => { const failedManual = current.filter(row => failures.includes(row.id)); return failedManual.length ? failedManual : [{ id: Date.now(), permalink: '', altText: '', description: '', primary: false }]; });
    if (failures.length) setError(`${failures.length} WorkDrive link${failures.length === 1 ? '' : 's'} failed. Successful links were added; retry the remaining rows.`);
    await onSaved(); setBusy(false);
  }
  return <section className="border-t border-stone-200 mt-6 pt-5"><div className="eyebrow">B · External media link</div><h3 className="font-display text-2xl mt-1">Add WorkDrive links</h3><p className="secondary-copy mt-2">Files remain external and are never uploaded to Cloudinary.</p><form onSubmit={submit} className="mt-4 space-y-4"><div><label className="text-sm font-semibold" htmlFor="workdrive-paste">Paste one or multiple WorkDrive links</label><textarea id="workdrive-paste" className="field min-h-32 mt-2" disabled={!canWrite || busy} value={pasteBlock} onChange={event => setPasteBlock(event.target.value)} placeholder={'filename.png - https://workdrive.zoho.in/file/...\nfilename-2.png - https://workdrive.zoho.in/file/...'} /><p className="text-xs text-stone-500 mt-2">You can paste one link or Zoho WorkDrive&apos;s multi-file copied format.</p><p className="text-xs font-semibold mt-1">Detected links: {detectedLinks.length}</p><label className="text-sm flex items-center gap-2 mt-2"><input type="checkbox" disabled={!canWrite || busy || !detectedLinks.length} checked={pastePrimary} onChange={event => setPastePrimary(event.target.checked)} /> Set first detected link as primary</label></div><div className="eyebrow">Manual link rows</div>{rows.map((row, index) => <div key={row.id} className="border border-stone-200 p-3"><div className="flex gap-2"><input className="field flex-1" type="url" disabled={!canWrite || busy} value={row.permalink} onChange={event => updateRow(row.id, { permalink: event.target.value })} placeholder="https://workdrive.zoho.in/file/..." aria-label={`WorkDrive permalink ${index + 1}`}/>{rows.length > 1 && <button className="text-xs text-red-700 underline px-2" type="button" disabled={busy} onClick={() => removeRow(row.id)}>Remove</button>}</div><div className="grid md:grid-cols-2 gap-2 mt-2"><input className="field" disabled={!canWrite || busy} value={row.altText} onChange={event => updateRow(row.id, { altText: event.target.value })} placeholder="Alt text"/><input className="field" disabled={!canWrite || busy} value={row.description} onChange={event => updateRow(row.id, { description: event.target.value })} placeholder="Description"/></div><label className="text-sm flex items-center gap-2 mt-2"><input type="checkbox" disabled={!canWrite || busy} checked={row.primary} onChange={event => updateRow(row.id, { primary: event.target.checked })} /> Set as primary</label>{row.error && <p className="text-xs text-red-700 mt-2">{row.error}</p>}</div>)}<div className="flex flex-wrap gap-3"><button className="button button-secondary" type="button" disabled={!canWrite || busy} onClick={addRow}>+ Add another link</button><button className="button" disabled={!canWrite || busy}>{busy ? 'Saving…' : 'Add WorkDrive links'}</button></div></form>{error && <p className="text-sm text-red-700 mt-3">{error}</p>}<p className="text-xs text-stone-500 mt-3">WorkDrive files are never downloaded, re-uploaded, or deleted by RK-STOCK.</p></section>;
}

function LegacyExternalMediaPanel({ product, canWrite, onSaved }: { product: Product; canWrite: boolean; onSaved: () => Promise<void> }) {
  const [rows, setRows] = useState<WorkDriveRow[]>([{ id: 1, permalink: '', altText: '', description: '', primary: false }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const permalink = ''; const altText = ''; const description = ''; const primary = false;
  const setPermalink = (_value: string) => undefined; const setAltText = (_value: string) => undefined; const setDescription = (_value: string) => undefined; const setPrimary = (_value: boolean) => undefined;
  function addRow() { setRows(current => [...current, { id: Date.now() + current.length, permalink: '', altText: '', description: '', primary: false }]); }
  function removeRow(id: number) { setRows(current => current.length === 1 ? current : current.filter(row => row.id !== id)); }
  function updateRow(id: number, changes: Partial<WorkDriveRow>) { setRows(current => current.map(row => row.id === id ? { ...row, ...changes, error: undefined } : row)); }
  function validPermalink(value: string) {
    try { const url = new URL(value.trim()); return url.protocol === 'https:' && (url.hostname.toLowerCase() === 'workdrive.zoho.in' || url.hostname.toLowerCase() === 'workdrive.zohoexternal.in') && !url.username && !url.password && Boolean(url.pathname); }
    catch { return false; }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const entered = rows.filter(row => row.permalink.trim());
    const invalid = entered.filter(row => !validPermalink(row.permalink));
    if (!entered.length) { setError('Add at least one WorkDrive permalink.'); setBusy(false); return; }
    if (invalid.length) { setRows(current => current.map(row => invalid.some(item => item.id === row.id) ? { ...row, error: 'Use an approved HTTPS WorkDrive permalink.' } : row)); setError('One or more WorkDrive links are invalid.'); setBusy(false); return; }
    if (entered.filter(row => row.primary).length > 1) { setError('Select at most one new primary media item.'); setBusy(false); return; }
    const failures: number[] = []; let position = product.images?.length || 0;
    for (const row of entered) {
      try { await api(`/products/${product._id}/media`, { method: 'POST', body: JSON.stringify({ provider: 'zoho_workdrive', type: 'image', permalink: row.permalink.trim(), source: 'rk-stock', position, is_primary: row.primary, alt_text: row.altText, description: row.description }) }); position += 1; }
      catch (value) { failures.push(row.id); setRows(current => current.map(item => item.id === row.id ? { ...item, error: value instanceof Error ? value.message : 'Unable to add this WorkDrive link.' } : item)); }
    }
    setRows(current => failures.length ? current.filter(row => failures.includes(row.id)) : [{ id: Date.now(), permalink: '', altText: '', description: '', primary: false }]);
    if (failures.length) setError(`${failures.length} WorkDrive link${failures.length === 1 ? '' : 's'} failed. Successful links were added; retry the remaining rows.`);
    await onSaved(); setBusy(false);
  }
  return <section className="card p-5 mb-4"><div className="eyebrow">B · External media link</div><h3 className="font-display text-2xl mt-1">Add WorkDrive link</h3><p className="secondary-copy mt-2">Paste an approved WorkDrive permalink. It remains an external relationship and is never uploaded to Cloudinary.</p><form onSubmit={submit} className="grid md:grid-cols-2 gap-3 mt-4"><input className="field md:col-span-2" type="url" required disabled={!canWrite || busy} value={permalink} onChange={event => setPermalink(event.target.value)} placeholder="https://workdrive.zoho.in/file/... or https://workdrive.zohoexternal.in/embed/..." aria-label="WorkDrive permalink"/><input className="field" disabled={!canWrite || busy} value={altText} onChange={event => setAltText(event.target.value)} placeholder="Alt text"/><input className="field" disabled={!canWrite || busy} value={description} onChange={event => setDescription(event.target.value)} placeholder="Description"/><label className="text-sm flex items-center gap-2"><input type="checkbox" disabled={!canWrite || busy} checked={primary} onChange={event => setPrimary(event.target.checked)} /> Set as primary</label><button className="button md:col-span-2" disabled={!canWrite || busy}>{busy ? 'Saving…' : 'Add WorkDrive link'}</button></form>{error && <p className="text-sm text-red-700 mt-3">{error}</p>}<p className="text-xs text-stone-500 mt-3">WorkDrive files are never downloaded, re-uploaded, or deleted by RK-STOCK.</p></section>;
}

export default function Page() {
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState({ collection: '', category: '', status: '', media: '', inventory: '', color: '', season: '', recent: '', source: '' });
  const [view, setView] = useState<'list' | 'grid'>('list');
  const [tab, setTab] = useState<Tab>('overview');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [canWrite, setCanWrite] = useState(false);
  const [collections, setCollections] = useState<any[]>([]);
  const [draft, setDraft] = useState<any>({});
  const [savedDraft, setSavedDraft] = useState<any>({});
  const pageSize = 24;

  const load = async () => {
    setLoading(true); setError('');
    try {
      const [result, configured] = await Promise.all([api<{ items: Product[] }>('/products?limit=500'), api<{ items: any[] }>('/collections')]);
      setProducts((result.items || []).map(product => ({ ...product, images: (product.images || []).map((image: any) => ({ ...image, product_id: product._id })) })));
      setCollections(configured.items || []);
      setSelectedId(current => current || result.items?.[0]?._id || '');
    } catch (value) { setError(value instanceof Error ? value.message : 'Unable to load products.'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  useEffect(() => { api<any>('/auth/me').then(user => setCanWrite((user.effective_permissions || []).includes('*') || (user.effective_permissions || []).includes('settings:write'))).catch(() => setCanWrite(false)); }, []);

  const options = useMemo(() => ({
    collections: [...new Set(products.flatMap(collectionNamesOf).filter(Boolean))].sort(),
    categories: [...new Set(products.map(product => product.category).filter(Boolean))].sort(),
    colors: [...new Set(products.flatMap(colorsOf).filter(Boolean))].sort(),
    seasons: [...new Set(products.map(product => product.season).filter(Boolean))].sort(),
    sources: [...new Set(products.map(product => product.source_system || product.source).filter(Boolean))].sort(),
  }), [products]);

  const filtered = useMemo(() => products.filter(product => {
    const haystack = [product.sku, product.name, product.product_code, product.vendor_code, product.category, collectionOf(product), ...colorsOf(product)].join(' ').toLowerCase();
    const updated = product.updated_at || product.updatedAt;
    const recentDays = filters.recent === '7' ? 7 : filters.recent === '30' ? 30 : 0;
    const recentEnough = !recentDays || (updated && !Number.isNaN(new Date(updated).getTime()) && Date.now() - new Date(updated).getTime() <= recentDays * 86400000);
    return (!query.trim() || haystack.includes(query.trim().toLowerCase()))
      && (!filters.collection || collectionNamesOf(product).includes(filters.collection))
      && (!filters.category || product.category === filters.category)
      && (!filters.status || statusOf(product) === filters.status)
      && (!filters.media || mediaStatus(product) === filters.media)
      && (!filters.inventory || inventoryStatus(product) === filters.inventory)
      && (!filters.color || colorsOf(product).includes(filters.color))
      && (!filters.season || product.season === filters.season)
      && (!filters.recent || recentEnough)
      && (!filters.source || (product.source_system || product.source) === filters.source);
  }), [products, query, filters]);
  const visible = filtered.slice((page - 1) * pageSize, page * pageSize);
  const selected = products.find(product => product._id === selectedId) || visible[0];
  const activeFilterCount = Object.values(filters).filter(Boolean).length;
  const hasInventoryData = products.some(product => typeof product.stock === 'number' || typeof product.available === 'number');
  const metrics = {
    active: products.filter(product => statusOf(product) === 'active').length,
    completeMedia: products.filter(product => mediaStatus(product) === 'Complete').length,
    missingPrimary: products.filter(product => mediaStatus(product) === 'Missing primary').length,
    noCollection: products.filter(product => !collectionOf(product)).length,
    recentlyUpdated: products.filter(product => product.updated_at || product.updatedAt).length,
  };

  useEffect(() => { setPage(1); }, [query, filters]);
  useEffect(() => { if (selected && selected._id !== selectedId) setSelectedId(selected._id); }, [selected, selectedId]);
  useEffect(() => { if (selected) { const next = draftFor(selected); setDraft(next); setSavedDraft(next); } }, [selected]);
  const hasUnsavedChanges = JSON.stringify(draft) !== JSON.stringify(savedDraft);

  function clearFilters() { setFilters({ collection: '', category: '', status: '', media: '', inventory: '', color: '', season: '', recent: '', source: '' }); setQuery(''); }
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return; const form = event.currentTarget; const payload = new FormData(form); setBusy(true); setError('');
    try { await api(`/products/${selected._id}/images`, { method: 'POST', body: payload }); await load(); form.reset(); }
    catch (value) { setError(value instanceof Error ? value.message : 'Upload failed.'); }
    finally { setBusy(false); }
  }
  async function updateMedia(payload: Record<string, any>) {
    if (!selected) return; setBusy(true); setError('');
    try { await api(`/products/${selected._id}/images`, { method: 'PATCH', body: JSON.stringify(payload) }); await load(); }
    catch (value) { setError(value instanceof Error ? value.message : 'Unable to update media.'); }
    finally { setBusy(false); }
  }
  async function retryStorefrontSync() {
    if (!selected) return; setBusy(true); setError('');
    try { await api(`/products/${selected._id}/sync-storefront`, { method: 'POST' }); await load(); }
    catch (value) { setError(value instanceof Error ? value.message : 'Unable to synchronize this product.'); await load(); }
    finally { setBusy(false); }
  }
  function moveMedia(index: number, offset: number) {
    if (!selected?.images) return; const order = selected.images.map((image: any) => image.id || image.url); const target = index + offset;
    if (target < 0 || target >= order.length) return; [order[index], order[target]] = [order[target], order[index]]; void updateMedia({ order });
  }
  async function removeMedia(image: any) {
    if (!selected) return;
    const message = image.provider === 'zoho_workdrive'
      ? 'Remove this WorkDrive media link from this product? The WorkDrive file itself will remain untouched.'
      : image.source === 'rk-stock'
        ? 'Remove this image? This will also permanently delete the uploaded image from Cloudinary.'
        : 'Remove this image from RK-STOCK? The source Cloudinary asset will not be deleted.';
    if (!window.confirm(message)) return;
    setBusy(true); setError('');
    try { await api(`/products/${selected._id}/images/${image.id}`, { method: 'DELETE' }); await load(); }
    catch (value) {
      if (value instanceof ApiError && value.status === 409) { await load(); setError('Media changed; refreshed. Please try again.'); }
      else setError(value instanceof Error ? value.message : 'Unable to remove media.');
    }
    finally { setBusy(false); }
  }
  async function saveProduct(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return; setBusy(true); setError('');
    try {
      await api(`/products/${selected._id}`, { method: 'PATCH', body: JSON.stringify({ ...draft, colors: String(draft.colors || '').split(',').map((value: string) => value.trim()).filter(Boolean), selling_price: Number(draft.selling_price), collection_ids: draft.collection_ids || [] }) });
      await load();
    } catch (value) { setError(value instanceof Error ? value.message : 'Unable to save product.'); }
    finally { setBusy(false); }
  }
  function resetDraft() { if (selected) setDraft(draftFor(selected)); }

  return <>
    <PageHeading eyebrow="Catalog operations" title="Products" description="Manage products, catalog information, media, collections, categories, variants and inventory visibility." />
    {selected && tab === 'variants' && <ProductVariantManager product={selected} canWrite={canWrite} />}
    {selected && tab === 'inventory' && <ProductInventoryManager product={selected} canWrite={canWrite} />}
    {selected && <ProductLifecycleActions product={selected} canWrite={canWrite} onSaved={load} />}
    {error && <ErrorState message={error} retry={load} />}
    {loading ? <Loading /> : products.length === 0 ? <Empty title="No products" detail="Create or import product records before managing the catalog." /> : <>
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-7">
        <Metric label="Total products" value={products.length} /><Metric label="Active products" value={metrics.active} /><Metric label="Complete media" value={metrics.completeMedia} /><Metric label="Missing primary" value={metrics.missingPrimary} /><Metric label="Without collection" value={metrics.noCollection} />
      </div>
      <div className="grid xl:grid-cols-[minmax(340px,.8fr)_minmax(0,1.7fr)] gap-6 items-start">
        <section className="card p-4 min-w-0">
          <div className="flex items-start justify-between gap-3 mb-4"><div><div className="eyebrow">Catalog index</div><h2 className="font-display text-2xl mt-1">All products</h2></div><div className="flex border border-stone-200"><button className={`px-3 py-2 text-xs ${view === 'list' ? 'bg-charcoal text-white' : ''}`} onClick={() => setView('list')}>List</button><button className={`px-3 py-2 text-xs ${view === 'grid' ? 'bg-charcoal text-white' : ''}`} onClick={() => setView('grid')}>Grid</button></div></div>
          <input className="field mb-3" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search SKU, name, code, colour…" aria-label="Search products" />
          <div className="grid sm:grid-cols-2 gap-2 mb-3">
            <select className="field" value={filters.collection} onChange={event => setFilters({ ...filters, collection: event.target.value })}><option value="">All collections</option>{options.collections.map(value => <option key={value}>{value}</option>)}</select>
            <select className="field" value={filters.category} onChange={event => setFilters({ ...filters, category: event.target.value })}><option value="">All categories</option>{options.categories.map(value => <option key={value}>{value}</option>)}</select>
            <select className="field" value={filters.status} onChange={event => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option>{['active', 'draft', 'archived'].filter(value => products.some(product => statusOf(product) === value)).map(value => <option key={value}>{value}</option>)}</select>
            <select className="field" value={filters.media} onChange={event => setFilters({ ...filters, media: event.target.value })}><option value="">All media</option><option>Complete</option><option>Missing primary</option></select>
            {hasInventoryData && <select className="field" value={filters.inventory} onChange={event => setFilters({ ...filters, inventory: event.target.value })}><option value="">All inventory</option><option>In stock</option><option>Out of stock</option></select>}
            {!!options.colors.length && <select className="field" value={filters.color} onChange={event => setFilters({ ...filters, color: event.target.value })}><option value="">All colours</option>{options.colors.map(value => <option key={value}>{value}</option>)}</select>}
            {!!options.seasons.length && <select className="field" value={filters.season} onChange={event => setFilters({ ...filters, season: event.target.value })}><option value="">All seasons</option>{options.seasons.map(value => <option key={value}>{value}</option>)}</select>}
            <select className="field" value={filters.recent} onChange={event => setFilters({ ...filters, recent: event.target.value })}><option value="">Any update date</option><option value="7">Updated in 7 days</option><option value="30">Updated in 30 days</option></select>
            {!!options.sources.length && <select className="field" value={filters.source} onChange={event => setFilters({ ...filters, source: event.target.value })}><option value="">All sources</option>{options.sources.map(value => <option key={value}>{value}</option>)}</select>}
          </div>
          {(activeFilterCount > 0 || query) && <div className="flex flex-wrap items-center gap-2 mb-4"><span className="text-xs text-stone-500">Active filters</span>{query && <button className="status" onClick={() => setQuery('')}>Search: {query} ×</button>}{Object.entries(filters).filter(([, value]) => value).map(([key, value]) => <button className="status" key={key} onClick={() => setFilters({ ...filters, [key]: '' })}>{key}: {value} ×</button>)}<button className="text-xs underline ml-auto" onClick={clearFilters}>Clear all</button></div>}
          <div className={`${view === 'grid' ? 'grid sm:grid-cols-2' : 'divide-y'} max-h-[68vh] overflow-auto`}>
            {visible.map(product => <button key={product._id} onClick={() => { setSelectedId(product._id); setTab('overview'); }} className={`w-full text-left p-3 transition ${selected?._id === product._id ? 'bg-[#f1eadf]' : 'hover:bg-[#faf7f0]'} ${view === 'grid' ? 'border border-stone-200' : ''}`}>
              <div className="flex gap-3"><ProductImage image={product.images?.find((image: any) => image.is_main) || product.images?.[0]} alt={product.name || product.sku || 'Product'} /><div className="min-w-0 flex-1"><div className="font-mono text-xs font-semibold truncate">{text(product.sku, 'No SKU')}</div><div className="font-semibold truncate mt-1">{text(product.name)}</div><div className="text-xs text-stone-500 truncate mt-1">{colorsOf(product).join(', ') || 'No colour'} · {text(collectionOf(product), 'No collection')}</div><div className="text-[11px] text-stone-500 mt-2">{product.images?.length || 0} media · {inventoryStatus(product)}</div></div><span className="status self-start">{statusOf(product)}</span></div>
            </button>)}
            {!visible.length && <div className="py-12 text-center text-sm text-stone-500">No products found. Try changing your filters.</div>}
          </div>
          <div className="flex items-center justify-between border-t border-stone-200 mt-4 pt-3 text-xs text-stone-500"><span>{filtered.length} matching · page {page} of {Math.max(1, Math.ceil(filtered.length / pageSize))}</span><div className="flex gap-2"><button className="button button-secondary !py-1" disabled={page === 1} onClick={() => setPage(value => value - 1)}>Previous</button><button className="button button-secondary !py-1" disabled={page >= Math.ceil(filtered.length / pageSize)} onClick={() => setPage(value => value + 1)}>Next</button></div></div>
        </section>
        <section className="min-w-0">
          {!selected ? <div className="card p-8 text-center text-stone-500">Select a product to inspect its catalog profile.</div> : <>
            <div className="card p-6 mb-4"><div className="flex flex-col md:flex-row gap-5 justify-between"><div><div className="eyebrow">Product profile</div><h2 className="font-display text-4xl mt-1">{text(selected.sku, 'Untitled product')}</h2><p className="text-stone-500 mt-2">{text(selected.name)} · {colorsOf(selected).join(', ') || 'Colour not specified'}</p></div><div className="flex gap-2 items-start"><span className="status">{statusOf(selected)}</span><button className="button button-secondary" onClick={() => setTab('media')}>Manage media</button></div></div><div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-6"><div><div className="text-xs text-stone-500">Category</div><div className="font-semibold mt-1">{text(selected.category)}</div></div><div><div className="text-xs text-stone-500">Collection</div><div className="font-semibold mt-1">{text(collectionOf(selected))}</div></div><div><div className="text-xs text-stone-500">Media</div><div className="font-semibold mt-1">{selected.images?.length || 0} files</div></div><div><div className="text-xs text-stone-500">Inventory</div><div className="font-semibold mt-1">{inventoryStatus(selected)}</div></div></div></div>
            <div className="product-workspace-statusbar"><ProductSyncStatus product={selected} onRetry={() => void retryStorefrontSync()} />{hasUnsavedChanges && <span className="product-unsaved">Unsaved changes</span>}</div>
            <div className="product-workspace-tabs flex gap-1 overflow-x-auto border-b border-stone-200 mb-5" role="tablist">{(['overview', 'media', 'variants', 'inventory', 'collections', 'history'] as Tab[]).map(value => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={`product-workspace-tab px-4 py-3 text-xs uppercase tracking-[.12em] whitespace-nowrap ${tab === value ? 'is-active' : ''}`}>{value}</button>)}</div>
            {tab === 'overview' && <form onSubmit={saveProduct} className="card p-6"><div className="eyebrow">Product master</div><div className="grid md:grid-cols-2 gap-4 mt-5"><label className="text-sm font-semibold">Product name<input className="field mt-2" value={draft.name || ''} onChange={e => setDraft({ ...draft, name: e.target.value })} disabled={!canWrite} required /></label><label className="text-sm font-semibold">SKU<input className="field mt-2" value={draft.sku || ''} onChange={e => setDraft({ ...draft, sku: e.target.value })} disabled={!canWrite} required /></label><label className="text-sm font-semibold">Product code<input className="field mt-2" value={draft.product_code || ''} onChange={e => setDraft({ ...draft, product_code: e.target.value })} disabled={!canWrite} required /></label><label className="text-sm font-semibold">Colour<input className="field mt-2" value={draft.colors || ''} onChange={e => setDraft({ ...draft, colors: e.target.value })} disabled={!canWrite} /></label><label className="text-sm font-semibold">Category<input className="field mt-2" value={draft.category || ''} onChange={e => setDraft({ ...draft, category: e.target.value })} disabled={!canWrite} required /></label><label className="text-sm font-semibold">Price<input className="field mt-2" type="number" min="0" step=".01" value={draft.selling_price ?? ''} onChange={e => setDraft({ ...draft, selling_price: e.target.value })} disabled={!canWrite} required /></label><label className="text-sm font-semibold md:col-span-2">Description<textarea className="field mt-2" value={draft.description || ''} onChange={e => setDraft({ ...draft, description: e.target.value })} disabled={!canWrite} rows={4} /></label><label className="text-sm font-semibold">Status<select className="field mt-2" value={draft.active ? 'active' : 'inactive'} onChange={e => setDraft({ ...draft, active: e.target.value === 'active' })} disabled={!canWrite}><option value="active">Active</option><option value="inactive">Inactive</option></select></label></div>{canWrite ? <div className="flex gap-3 mt-5"><button className="button" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</button><button type="button" className="button button-secondary" onClick={resetDraft}>Reset</button></div> : <p className="secondary-copy mt-5">Read-only access. The settings:write permission is required to edit products.</p>}</form>}
            {tab === 'media' && <div className="card p-6"><div className="flex items-center justify-between gap-3"><div><div className="eyebrow">Product media</div><h3 className="font-display text-2xl mt-1">Fashion catalogue imagery</h3><p className="secondary-copy mt-2">Cloudinary uploads and external media links are managed separately. Stored order and primary state are preserved.</p></div><span className="status">{selected.images?.length || 0} files</span></div><div className="eyebrow mt-6">A · Upload photos</div><form onSubmit={upload} className="product-media-upload grid md:grid-cols-2 gap-3 mt-3"><input className="field md:col-span-2" name="files" type="file" accept="image/jpeg,image/png,image/webp" multiple required/><select className="field" name="view"><option value="main">Main product image</option><option value="front">Front view</option><option value="back">Back view</option><option value="side">Side view</option><option value="detail">Detail image</option><option value="reference">Reference image</option></select><input className="field" name="description" placeholder="Image description"/><input type="hidden" name="collection" value={collectionOf(selected) || ''}/><button className="button md:col-span-2" disabled={busy}>{busy ? 'Uploading…' : 'Upload Cloudinary images'}</button></form><ExternalMediaPanel product={selected} canWrite={canWrite} onSaved={load} />{selected.images?.length ? <><div className="eyebrow mt-6">Existing media</div><div className="product-media-grid grid grid-cols-2 md:grid-cols-3 gap-4 mt-3">{selected.images.map((image: any, index: number) => <div className="product-media-card border border-stone-200 p-3" key={image.id || imageUrl(image) || index}><ProductImage image={image} large alt={`${selected.name || selected.sku || 'Product'} ${index + 1}`} />{image.provider === 'zoho_workdrive' && image.permalink && <div className="mt-3 text-xs"><div className="font-semibold">WorkDrive · External media</div><a className="underline" href={image.permalink} target="_blank" rel="noreferrer">Open WorkDrive</a></div>}<div className="text-xs font-semibold truncate mt-3">{text(image.view, image.is_main ? 'Primary image' : 'Gallery image')}</div><div className="text-[11px] text-stone-500 truncate mt-1">{text(image.filename || image.permalink || imageUrl(image))}</div>{image.description && <div className="text-[11px] text-stone-600 mt-2">{image.description}</div>}<div className="flex flex-wrap gap-2 mt-3"><button className="text-xs underline" type="button" disabled={!canWrite || busy} onClick={() => void updateMedia({ primary_id: image.id })}>{image.is_main || image.is_primary ? 'Primary' : 'Set primary'}</button><button className="text-xs underline" type="button" disabled={!canWrite || busy || index === 0} onClick={() => moveMedia(index, -1)}>Move left</button><button className="text-xs underline" type="button" disabled={!canWrite || busy || index === selected.images.length - 1} onClick={() => moveMedia(index, 1)}>Move right</button><button className="text-xs text-red-700 underline" type="button" disabled={!canWrite || busy} onClick={() => void removeMedia(image)}>Remove</button></div>{(image.is_main || image.is_primary) && <span className="status inline-block mt-2">Primary</span>}</div>)}</div></> : <div className="border border-dashed border-stone-300 p-8 text-center mt-7"><div className="font-display text-2xl">No media uploaded</div><p className="text-sm text-stone-500 mt-2">Add product imagery to complete this product&apos;s catalogue profile.</p></div>}</div>}
            {tab === 'details' && <div className="card p-6"><div className="eyebrow">Product details</div><div className="grid sm:grid-cols-2 gap-x-8 gap-y-5 mt-5">{[['SKU', selected.sku], ['Product name', selected.name], ['Product code', selected.product_code], ['Vendor code', selected.vendor_code], ['Category', selected.category], ['Collection', collectionOf(selected)], ['Season', selected.season], ['Slug', selected.slug], ['Currency', selected.base_currency || selected.currency], ['Tax inclusive', selected.tax_inclusive === undefined ? undefined : selected.tax_inclusive ? 'Yes' : 'No']].map(([label, value]) => <div key={String(label)}><div className="text-xs text-stone-500">{label}</div><div className="font-semibold mt-1 break-words">{text(value)}</div></div>)}</div>{(selected.description || selected.notes) && <div className="border-t border-stone-200 mt-7 pt-5"><div className="text-xs text-stone-500">Description</div><p className="mt-2 text-sm leading-6">{selected.description || selected.notes}</p></div>}</div>}
            {tab === 'variants' && <div className="card p-6"><div className="eyebrow">Variants and configurations</div>{selected.variants?.length ? <div className="table-wrap mt-5"><table><thead><tr><th>SKU</th><th>Colour</th><th>Size</th><th>Status</th></tr></thead><tbody>{selected.variants.map((variant: any, index: number) => <tr key={variant._id || variant.id || index}><td>{text(variant.sku)}</td><td>{text(variant.color || variant.colour)}</td><td>{text(variant.size)}</td><td>{text(variant.status)}</td></tr>)}</tbody></table></div> : <p className="text-sm text-stone-500 mt-5">No product variants are embedded in the current product response.</p>}</div>}
            {tab === 'inventory' && <div className="card p-6"><div className="eyebrow">Operational inventory</div>{hasInventoryData && (selected.stock !== undefined || selected.available !== undefined) ? <div className="grid grid-cols-3 gap-4 mt-5"><div><div className="text-xs text-stone-500">Physical</div><div className="font-display text-3xl mt-1">{text(selected.physical)}</div></div><div><div className="text-xs text-stone-500">Reserved</div><div className="font-display text-3xl mt-1">{text(selected.reserved)}</div></div><div><div className="text-xs text-stone-500">Available</div><div className="font-display text-3xl mt-1">{text(selected.available ?? selected.stock)}</div></div></div> : <p className="text-sm text-stone-500 mt-5">Product inventory quantities are not included in the current catalog response. Use the Inventory workspace for ledger-backed stock operations.</p>}</div>}
            {tab === 'collections' && <div className="card p-6"><div className="eyebrow">Collection assignment</div><h3 className="font-display text-2xl mt-2">{text(collectionOf(selected), 'No collection assigned')}</h3><p className="text-sm text-stone-500 mt-3">Select every collection that owns this product. Aakaar is not assigned automatically.</p><div className="grid sm:grid-cols-2 gap-3 mt-5">{collections.map(collection => <label key={collection._id} className="flex gap-2 items-center text-sm"><input type="checkbox" checked={(draft.collection_ids || []).includes(String(collection._id))} disabled={!canWrite || busy} onChange={event => setDraft({ ...draft, collection_ids: event.target.checked ? [...(draft.collection_ids || []), String(collection._id)] : (draft.collection_ids || []).filter((id: string) => id !== String(collection._id)) })} />{collection.name}</label>)}</div>{canWrite && <button className="button mt-5" type="button" disabled={busy} onClick={() => void saveProduct({ preventDefault: () => {} } as FormEvent<HTMLFormElement>)}>Save collections</button>}</div>}
            {tab === 'history' && <div className="card p-6"><div className="eyebrow">History</div><p className="text-sm text-stone-500 mt-3">Product edits are recorded in the existing activity log. A dedicated product history view is not yet available.</p></div>}
          </>}
        </section>
      </div>
    </>}
  </>;
}
