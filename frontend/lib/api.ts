export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000/api';

export function token() { return typeof window === 'undefined' ? null : sessionStorage.getItem('rk_token'); }

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const auth = token();
  if (auth) headers.set('Authorization', `Bearer ${auth}`);
  const response = await fetch(`${API_URL}${path}`, { ...options, headers, cache: 'no-store' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined' && !path.includes('/auth/login')) { sessionStorage.removeItem('rk_token'); window.location.href = '/login'; }
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data as T;
}

export const formatNumber = (value?: number) => new Intl.NumberFormat('en-IN').format(value || 0);
export const formatMoney = (value?: string | number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(Number(value || 0));
