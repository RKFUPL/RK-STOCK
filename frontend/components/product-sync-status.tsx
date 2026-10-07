'use client';

type ProductSyncStatusProps = { product: Record<string, any>; onRetry: () => void };

export function ProductSyncStatus({ product, onRetry }: ProductSyncStatusProps) {
  const rawStatus = String(product.storefront_sync_status || product.sync_status || product.catalog_sync_status || product.sync?.status || '').toLowerCase();
  const lastSynced = product.storefront_last_synced_at || product.last_synced_at || product.catalog_last_synced_at || product.sync?.last_synced_at;
  const error = product.storefront_sync_error || product.sync_error || product.catalog_sync_error || product.sync?.error;
  const failed = rawStatus === 'failed' || rawStatus === 'error' || Boolean(error);
  const pending = !failed && ['pending', 'queued', 'syncing', 'in_progress'].includes(rawStatus);
  const synced = !failed && !pending && Boolean(lastSynced || rawStatus === 'synced' || rawStatus === 'success');
  return <div className="product-sync-status" aria-live="polite">
    <span className={`product-sync-dot ${failed ? 'is-failed' : pending ? 'is-pending' : synced ? 'is-synced' : ''}`} />
    <div><div className="product-sync-label">{failed ? 'Sync failed' : pending ? 'Sync pending' : synced ? 'Synced' : 'Not synchronized'}</div>
      {lastSynced && <div className="product-sync-meta">Last synced: {new Date(lastSynced).toLocaleString()}</div>}
      {failed && <button type="button" className="product-sync-retry" onClick={onRetry}>Retry</button>}
    </div>
  </div>;
}
