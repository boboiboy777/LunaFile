# AIF Webhook Gateway

Website Node.js serverless untuk asisten file AI dan gateway webhook di Vercel. Endpoint Telekos memverifikasi signature HMAC-SHA256 dan timestamp dengan format receiver lokal AIF. Asisten file adalah tahap awal migrasi dari bot Python; bot lama tetap dapat berjalan.

## Deploy

1. Import folder `webhook_site` sebagai project Vercel baru (atau atur **Root Directory** ke `webhook_site`).
2. Buat bot melalui BotFather, mulai chat dengan bot tersebut, lalu masukkan token bot sebagai `TELEGRAM_BOT_TOKEN` dan ID tujuan sebagai `TELEGRAM_CHAT_ID`.
3. Tambahkan `WEBHOOK_API_KEY` untuk endpoint umum dan `TELEKOS_WEBHOOK_SECRET` untuk Telekos.
4. Untuk asisten file, isi `APINEX_API_KEY` dan `AI_WEB_ACCESS_KEY`. Kunci akses web adalah kunci bersama yang diberikan kepada pengguna; endpoint tertutup jika belum diisi.
5. Deploy ulang. Buka `/app.html` untuk asisten file atau `/` untuk gateway webhook.

Simpan semua nilai pada Vercel → Project → Settings → Environment Variables. Jangan menaruh token atau secret di halaman website atau Git.

## Endpoint

- `POST /api/webhook` — JSON object dengan `Authorization: Bearer <WEBHOOK_API_KEY>` atau `X-Webhook-Secret`.
- `POST /api/telekos` — payload Telekos mentah, `X-Telekos-Signature`, dan `X-Telekos-Delivery`.
- `GET /api/health` — status konfigurasi tanpa membocorkan nilai secret.
- `POST /api/ask` — ekstrak PDF, DOCX, atau file teks lalu bertanya ke API AI. Wajib memakai `Authorization: Bearer <AI_WEB_ACCESS_KEY>`.

Contoh:

```sh
curl -X POST https://DOMAIN-VERCEL/api/webhook \
  -H 'Authorization: Bearer WEBHOOK_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"event":"order.created","id":"123"}'
```

Gateway meneruskan event sebagai notifikasi ke satu chat dan tidak menyimpan riwayat. Telekos yang dikirim langsung ke gateway ini akan memberi notifikasi ke chat admin; gateway tidak mengubah saldo atau status pesanan SQLite di bot lokal. Untuk pemrosesan order yang sudah ada di bot lokal, webhook tetap perlu diarahkan ke receiver lokal melalui tunnel HTTPS.

Untuk `TELEGRAM_CHAT_ID`, buka chat dengan bot penerima dan kirim `/start`. Ambil ID akun melalui bot seperti `@userinfobot` untuk chat pribadi; untuk grup, tambahkan bot ke grup dan gunakan ID grup dari update Telegram.


## Asisten file web (tahap awal migrasi)

Halaman `/app.html` menerima PDF, DOCX, TXT, MD, CSV, LOG, JSON, XML, HTML, YAML, dan INI hingga 2 MB. Backend mengekstrak teks, membatasi konten ke 100.000 karakter, lalu mengirim pertanyaan dan konten file ke penyedia AI yang dikonfigurasi. Isi file tidak disimpan oleh aplikasi. `AI_API_URL` dan `AI_MODEL` dapat disesuaikan; `APINEX_API_KEY` hanya dibaca backend.

Atur `APINEX_API_KEY` dan `AI_WEB_ACCESS_KEY` di Vercel → Project → Settings → Environment Variables. Pengguna memasukkan kunci akses bersama di halaman; jangan menaruhnya di kode atau membagikannya secara publik. Belum ada akun individual, kuota per pengguna, riwayat, database, pembayaran, atau integrasi paket Premium pada versi web ini. Fitur tersebut perlu dimigrasikan terpisah sebelum seluruh bot digantikan.

Untuk menjalankan secara lokal, masuk ke folder `webhook_site`, jalankan `npm install`, salin `.env.example` menjadi `.env.local`, isi variabel yang dibutuhkan, lalu `npm run dev` (perlu Vercel CLI).
