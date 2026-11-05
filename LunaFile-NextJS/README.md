# LunaFile Bot — Next.js (JavaScript)

Migrasi LunaFile ke Next.js App Router tanpa TypeScript. Halaman Next.js menyediakan beranda, panel admin, health endpoint, endpoint webhook Telegram, serta webhook OTP Telekos. Bot memakai Webhook Telegram (bukan polling) dan database SQLite bawaan Node.

**Catatan:** proyek ini berdiri terpisah dari bot Python yang sedang berjalan. Jangan pasang webhook Telegram untuk bot yang sama sebelum menghentikan bot Python, karena long polling dan webhook tidak bisa aktif bersamaan.

## Persyaratan Termux

- Node.js 22.5 atau lebih baru (Node 24 disarankan), npm, `yt-dlp`, `unzip`, dan `poppler` (`pdftotext`).
- URL HTTPS publik untuk Telegram dan Telekos webhook. Next.js dapat tetap bind ke `127.0.0.1`; gunakan tunnel/reverse proxy yang sudah dipakai untuk meneruskan URL publik ke port lokal 3000.

## Menyiapkan proyek

```sh
cp .env.example .env
# Isi semua secret sendiri di .env
npm install
npm run check
npm run build
./server.sh start
```

Buka `http://127.0.0.1:3000`. Panel admin ada di `/admin`, memakai nilai `ADMIN_PASSWORD`.

Atur `WEBHOOK_BASE_URL` ke origin HTTPS publik, buat `TELEGRAM_WEBHOOK_SECRET` acak dengan huruf/angka/`_`/`-`, lalu jalankan `npm run webhook:set`. Setelah URL aktif, hentikan polling bot Python lama. Untuk kembali ke polling Python, jalankan `npm run webhook:delete` terlebih dahulu.

Webhook Telekos diarahkan ke `https://domain-anda/api/webhooks/telekos`. Atur `TELEKOS_WEBHOOK_SECRET` di `.env` dan gunakan secret yang sama di pengaturan Telekos.

## Data dan kompatibilitas

`admin_stats.sqlite3` adalah salinan database SQLite bot Python saat migrasi dibuat. Skema dipertahankan agar statistik, kuota, status Premium, pembayaran, saldo, pesanan, dan tugas Airdrop tetap terbaca. Bot Node memakai file database di direktori proyek ini; backup file tersebut secara berkala. Jangan salin `.env` ke folder publik atau bagikan isinya.

Variabel konfigurasi ada di `.env.example`. Nilai API key dan password sengaja dikosongkan. Kunci Sandbox yang pernah berada di contoh Python tidak disalin.

## Fitur yang telah dipindahkan

- Telegram: menu, akses channel, file dan jawaban AI, kuota, Premium, redeem, Airdrop, perintah unduh video, dan kontrol admin utama.
- Beli nomor Telekos: server, aplikasi (WhatsApp di urutan pertama), negara (Indonesia di urutan pertama), pencarian negara, daftar harga dengan stok, pembelian, pemeriksaan OTP, pembatalan, dan saldo internal.
- Midtrans QRIS untuk Premium dan top up saldo; pembayaran dapat dicek lewat tombol setelah transaksi.
- Webhook OTP Telekos bertanda tangan HMAC dan deduplikasi delivery.
- Panel admin Next.js untuk statistik pengguna/AI.

PDF memakai `pdftotext`; DOCX dan ZIP memakai `unzip`; video memakai `yt-dlp`. Format Office berpassword dan inspeksi APK belum tersedia pada migrasi JavaScript. Beberapa tindakan admin Python yang lebih rinci (riwayat chat lengkap, broadcast, dan penghapusan data lanjutan) belum dipindahkan.
