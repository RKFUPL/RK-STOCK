import { NextRequest, NextResponse } from 'next/server';

const hopByHopHeaders = new Set(['connection', 'content-length', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer', 'transfer-encoding', 'upgrade', 'host']);

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  if (process.env.NODE_ENV === 'production') {
    return NextResponse.json({ error: 'The local development API proxy is disabled in production.' }, { status: 404 });
  }

  const target = (process.env.RK_LOCAL_API_PROXY_TARGET || '').trim().replace(/\/$/, '');
  if (!target) {
    return NextResponse.json({ error: 'Local API proxy is not configured. Set RK_LOCAL_API_PROXY_TARGET.' }, { status: 503 });
  }

  let targetUrl: URL;
  try {
    targetUrl = new URL(target);
    const loopbackHost = ['localhost', '127.0.0.1', '[::1]'].includes(targetUrl.hostname);
    const localTarget = targetUrl.protocol === 'http:' && loopbackHost && targetUrl.port === '5006';
    const remoteTarget = targetUrl.protocol === 'https:' && !loopbackHost;
    if (!localTarget && !remoteTarget) throw new Error('unsafe proxy target');
  } catch {
    return NextResponse.json({ error: 'Local API proxy target is invalid.' }, { status: 503 });
  }

  const { path } = await context.params;
  const upstream = `${target}/api/${path.map(segment => encodeURIComponent(segment)).join('/')}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const [name, value] of request.headers) {
    if (!hopByHopHeaders.has(name.toLowerCase()) && ['authorization', 'content-type', 'accept'].includes(name.toLowerCase())) headers.set(name, value);
  }

  try {
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: 'no-store',
    });
    const responseHeaders = new Headers();
    for (const [name, value] of response.headers) if (!hopByHopHeaders.has(name.toLowerCase())) responseHeaders.set(name, value);
    return new NextResponse(response.body, { status: response.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ error: 'The configured API is unreachable.' }, { status: 502 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
