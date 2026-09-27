export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000/api';
export class ApiError extends Error { constructor(message: string, public status?: number) { super(message); this.name = 'ApiError'; } }

function requestError(path: string, status?: number, message?: string) {
  if (status === 401) return new ApiError(message || 'Invalid username or password.', status);
  if (status === 403) return new ApiError(message || 'Access denied. Your session is preserved.', status);
  if (status && status >= 500) return new ApiError(message || 'The server could not complete this request. Please try again.', status);
  if (!status) return new ApiError('Backend unreachable. Your session is preserved. Some features are temporarily unavailable.');
  return new ApiError(message || `Request failed (${status})`, status);
}

export function token() { return typeof window === 'undefined' ? null : sessionStorage.getItem('rk_token'); }

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const auth = token();
  if (auth) headers.set('Authorization', `Bearer ${auth}`);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...options, headers, cache: 'no-store' });
  } catch {
    throw requestError(path);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined' && !path.includes('/auth/login')) { sessionStorage.removeItem('rk_token'); window.location.href = '/login'; }
    throw requestError(path, response.status, data.error);
  }
  return data as T;
}

export async function download(path: string, filename: string) {
  const auth = token();
  const response = await fetch(`${API_URL}${path}`, { headers: auth ? { Authorization: `Bearer ${auth}` } : {}, cache: 'no-store' });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw requestError(path, response.status, data.error);
  }
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  URL.revokeObjectURL(url);
}

export async function authenticatedBlobUrl(path: string) {
  const auth = token();
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { headers: auth ? { Authorization: `Bearer ${auth}` } : {}, cache: 'no-store' });
  } catch {
    throw requestError(path);
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw requestError(path, response.status, data.error);
  }
  return URL.createObjectURL(await response.blob());
}

export const formatNumber = (value?: number) => new Intl.NumberFormat('en-IN').format(value || 0);
export const formatMoney = (value?: string | number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(Number(value || 0));
