import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = { title: 'RK Fashion Operations', description: 'Internal linesheet, stock, order and production portal' };
export default function RootLayout({ children }: Readonly<{children: React.ReactNode}>) { return <html lang="en"><body>{children}</body></html>; }
