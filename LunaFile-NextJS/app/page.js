import Link from 'next/link';

export default function HomePage() {
  return <main className="shell">
    <div className="brand">🌙 LunaFile</div>
    <h1>Telegram bot dashboard</h1>
    <p className="muted">Bot Telegram, panel admin, dan webhook Telekos berjalan melalui aplikasi Next.js ini.</p>
    <div className="grid">
      <Link className="card" href="/admin"><span>🔐</span><h2>Panel admin</h2><p>Lihat aktivitas dan statistik bot.</p></Link>
      <a className="card" href="/api/health"><span>💚</span><h2>Status layanan</h2><p>Periksa endpoint aplikasi.</p></a>
    </div>
  </main>;
}
