'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

const sizes = ['XS', 'S', 'M', 'L', 'XL'];

export function ProductVariantManager({ product, canWrite }: { product: any; canWrite: boolean }) {
  const [items, setItems] = useState<any[]>([]);
  const [size, setSize] = useState('M');
  const [sku, setSku] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => { try { const result = await api<{ items: any[] }>(`/products/${product._id}/variants`); setItems(result.items || []); } catch (value) { setError(value instanceof Error ? value.message : 'Unable to load variants.'); } };
  useEffect(() => { void load(); }, [product._id]);
  async function add() { setBusy(true); setError(''); try { await api(`/products/${product._id}/variants`, { method: 'POST', body: JSON.stringify({ size, inventory_sku: sku || undefined }) }); setSku(''); await load(); } catch (value) { setError(value instanceof Error ? value.message : 'Unable to add variant.'); } finally { setBusy(false); } }
  async function toggle(item: any) { setBusy(true); setError(''); try { await api(`/products/${product._id}/variants/${item._id}`, { method: 'PATCH', body: JSON.stringify({ active: item.active === false }) }); await load(); } catch (value) { setError(value instanceof Error ? value.message : 'Unable to update variant.'); } finally { setBusy(false); } }
  async function remove(item: any) { if (!window.confirm('Remove this variant? Historical variants cannot be removed.')) return; setBusy(true); setError(''); try { await api(`/products/${product._id}/variants/${item._id}`, { method: 'DELETE' }); await load(); } catch (value) { setError(value instanceof Error ? value.message : 'Unable to remove variant.'); } finally { setBusy(false); } }
  return <div className="card p-6"><div className="eyebrow">Size variants</div><p className="text-sm text-stone-500 mt-2">Variants use the existing inventory model and supported sizes: XS, S, M, L and XL.</p>{canWrite && <div className="grid sm:grid-cols-[140px_1fr_auto] gap-3 mt-5"><select className="field" value={size} onChange={event => setSize(event.target.value)}>{sizes.map(value => <option key={value}>{value}</option>)}</select><input className="field" value={sku} onChange={event => setSku(event.target.value)} placeholder="Variant SKU (optional)"/><button className="button" type="button" disabled={busy} onClick={() => void add()}>Add variant</button></div>}{error && <p className="notice notice-error mt-4">{error}</p>}<div className="table-wrap mt-5"><table><thead><tr><th>Size</th><th>Variant code</th><th>Status</th><th>Stock</th>{canWrite && <th>Actions</th>}</tr></thead><tbody>{items.map(item => <tr key={item._id}><td>{item.size}</td><td className="font-mono text-xs">{item.inventory_sku}</td><td>{item.active === false ? 'Archived' : 'Active'}</td><td>{typeof item.available === 'number' ? item.available : 'Not available'}</td>{canWrite && <td className="flex gap-3"><button type="button" className="text-xs underline" disabled={busy} onClick={() => void toggle(item)}>{item.active === false ? 'Activate' : 'Disable'}</button><button type="button" className="text-xs text-red-700 underline" disabled={busy} onClick={() => void remove(item)}>Remove</button></td>}</tr>)}{!items.length && <tr><td colSpan={canWrite ? 5 : 4} className="text-sm text-stone-500 py-5">No variants configured.</td></tr>}</tbody></table></div></div>;
}
