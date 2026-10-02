'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export function ProductInventoryManager({ product, canWrite }: { product: any; canWrite: boolean }) {
  const [items, setItems] = useState<any[]>([]);
  const [variantId, setVariantId] = useState('');
  const [quantity, setQuantity] = useState('');
  const [direction, setDirection] = useState('add');
  const [reason, setReason] = useState('manual_adjustment');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const load = async () => { try { const result = await api<{ items: any[] }>(`/products/${product._id}/inventory`); setItems(result.items || []); if (!variantId && result.items?.[0]) setVariantId(result.items[0]._id); } catch (value) { setError(value instanceof Error ? value.message : 'Unable to load inventory.'); } };
  useEffect(() => { void load(); }, [product._id]);
  async function submit() { setBusy(true); setError(''); setMessage(''); try { await api(`/products/${product._id}/inventory/adjust`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ variant_id: variantId, quantity: Number(quantity), direction, reason, notes }) }); setQuantity(''); setNotes(''); setMessage('Stock movement recorded in the ledger.'); await load(); } catch (value) { setError(value instanceof Error ? value.message : 'Unable to record stock movement.'); } finally { setBusy(false); } }
  return <div className="card p-6"><div className="eyebrow">Inventory position</div><p className="text-sm text-stone-500 mt-2">Balances are calculated from ledger-backed stock balances. Manual changes always create a ledger entry.</p><div className="table-wrap mt-5"><table><thead><tr><th>Size</th><th>Available</th><th>Reserved</th><th>Total</th></tr></thead><tbody>{items.map(item => <tr key={item._id}><td>{item.size}</td><td>{item.available}</td><td>{item.reserved}</td><td>{item.total}</td></tr>)}{!items.length && <tr><td colSpan={4} className="text-sm text-stone-500 py-5">No inventory variants configured.</td></tr>}</tbody></table></div>{canWrite && items.length > 0 && <div className="border-t border-stone-200 mt-6 pt-6"><div className="eyebrow">Stock adjustment</div><div className="grid md:grid-cols-2 gap-3 mt-4"><select className="field" value={variantId} onChange={event => setVariantId(event.target.value)}>{items.map(item => <option key={item._id} value={item._id}>{item.size} · {item.inventory_sku}</option>)}</select><div className="grid grid-cols-2 gap-3"><select className="field" value={direction} onChange={event => setDirection(event.target.value)}><option value="add">+ Add stock</option><option value="remove">− Remove stock</option></select><input className="field" type="number" min="1" value={quantity} onChange={event => setQuantity(event.target.value)} placeholder="Quantity" required /></div><select className="field" value={reason} onChange={event => setReason(event.target.value)}><option value="production_received">Production received</option><option value="manual_adjustment">Manual adjustment</option><option value="damage">Damage</option><option value="return">Return</option><option value="transfer">Transfer</option><option value="consignment">Consignment</option><option value="other">Other</option></select><input className="field" value={notes} onChange={event => setNotes(event.target.value)} placeholder="Notes" required /></div><button className="button mt-4" type="button" disabled={busy || !quantity} onClick={() => void submit()}>{busy ? 'Recording…' : 'Record movement'}</button></div>}{message && <p className="notice notice-success mt-4">{message}</p>}{error && <p className="notice notice-error mt-4">{error}</p>}</div>;
}
