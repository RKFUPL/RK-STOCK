'use client';

import { useState } from 'react';
import { api } from '@/lib/api';

export function ProductLifecycleActions({ product, canWrite, onSaved }: { product: any; canWrite: boolean; onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const archived = product.active === false || product.status === 'archived';
  async function setActive(active: boolean) {
    const message = active ? 'Reactivate this product? It will appear in active operational/product selection views again.' : 'Archive product? This product will no longer appear as active. Historical records will remain.';
    if (!window.confirm(message)) return;
    setBusy(true); setError('');
    try { await api(`/products/${product._id}`, { method: 'PATCH', body: JSON.stringify({ active }) }); onSaved(); }
    catch (value) { setError(value instanceof Error ? value.message : 'Unable to update product lifecycle.'); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!window.confirm('Delete product? This is permanent and is allowed only when no historical or operational records reference it.')) return;
    setBusy(true); setError('');
    try { await api(`/products/${product._id}`, { method: 'DELETE' }); onSaved(); }
    catch (value) { setError(value instanceof Error ? value.message : 'Product cannot be deleted. Archive it instead.'); }
    finally { setBusy(false); }
  }
  if (!canWrite) return null;
  return <div className="flex flex-wrap gap-2 items-start"><button className="button button-secondary" type="button" disabled={busy} onClick={() => void setActive(!archived)}>{busy ? 'Saving…' : archived ? 'Reactivate' : 'Archive'}</button><button className="text-xs text-red-700 underline px-2" type="button" disabled={busy} onClick={() => void remove()}>Delete permanently</button>{error && <p className="notice notice-error w-full mt-2">{error}</p>}</div>;
}
