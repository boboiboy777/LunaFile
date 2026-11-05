# Telegram File Reader Bot

Bot Telegram untuk membaca file dan mengunduh video dari YouTube, Instagram (Reels, postingan, dan Story), TikTok, serta Facebook. Mendukung TXT, JSON, DOCX, PDF, arsip ZIP, dan inspeksi awal APK.

## Menjalankan

1. Buat bot melalui BotFather dan salin tokennya.
2. Siapkan API key Apinex.
3. Buat virtual environment, pasang dependensi, lalu atur variabel lingkungan.

Di Termux, pasang `cryptography` dari repositori Termux lebih dulu dan buat virtual environment yang dapat memakai paket sistem. Ini menghindari build `cryptography` dari source oleh pip:

```sh
pkg install python-cryptography
python -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Di lingkungan Python lain, gunakan langkah standar:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Isi `TELEGRAM_BOT_TOKEN` dan `APINEX_API_KEY` di `.env`. Untuk nomor virtual, atur `TELEKOS_API_KEY`; untuk top up QRIS, atur `MIDTRANS_SERVER_KEY` serta konfigurasi Midtrans di bagian pembayaran. Bot membaca file `.env` otomatis; tidak perlu ekspor variabel. Jalankan:

```sh
python bot.py
```

Kode bot dipisah per fitur: `bot.py` menangani titik masuk, halaman awal, dan alur umum; `nav.py` menangani navigasi; `num.py` menangani katalog dan pesanan nomor; `vid.py` menangani video downloader; `file.py` menangani pemrosesan file; `airdrop.py` menangani garapan airdrop; `invite.py` menangani undangan; dan `buy.py` menangani pembelian Premium serta pembayaran QRIS.


### Admin panel di Telegram

Kirim `/myid` ke bot untuk mengetahui ID Telegram Anda. Tambahkan ID tersebut ke `ADMIN_TELEGRAM_IDS` di `.env` (pisahkan beberapa ID dengan koma), lalu mulai ulang layanan: `./server.sh stop && ./server.sh start`. Setelah itu, buka panel melalui `/admin` di chat bot. Hanya ID dalam daftar yang dapat melihat panel dan menekan tombolnya.

Panel menyediakan ringkasan statistik, daftar pengguna, rincian penggunaan AI per pengguna, dan menu **Kode redeem**. Dari menu itu admin dapat membuat kode dengan memasukkan durasi dan batas pengguna, misalnya `1 10` untuk Premium 1 hari bagi maksimal 10 pengguna. Pengguna menukarkan kode dengan `/redeem KODE`; satu pengguna hanya dapat memakai kode yang sama sekali dan jumlah klaim dibatasi sesuai pengaturan kode. Admin juga dapat mengaktifkan Premium 30 hari dari halaman detail pengguna; admin perlu mengonfirmasi pembayaran terlebih dahulu di luar bot. Pengguna dapat melihat paket dan kuotanya melalui `/paket` atau `/dashboard`. Dari detail pengguna, admin dapat memblokir atau membuka blokir akses bot, menghapus konteks chat dan file terakhir yang tersimpan dalam sesi, atau menghapus pengguna beserta statistik dan riwayat panggilan AI (dengan konfirmasi). Bot tidak menyimpan isi pesan sebagai arsip; penghapusan riwayat membersihkan konteks percakapan yang dipakai bot, bukan menghapus pesan dari chat Telegram. Token berasal dari field `usage` respons API; bila penyedia tidak mengirim field tersebut, pemakaian ditandai tidak dilaporkan. Data aktivitas baru tercatat sejak fitur ini dipasang.

### Garapan Airdrop

Pengguna dapat membuka daftar garapan melalui tombol **Garapan Airdrop** di menu atau perintah `/airdrop`. Daftar menampilkan nama, deskripsi, dan tautan HTTPS yang ditambahkan admin. Admin membuka `/admin` → **Garapan Airdrop**, lalu dapat menambahkan nama, deskripsi, dan tautan atau menghapus garapan dengan konfirmasi. Fitur ini berfungsi sebagai katalog tautan; belum ada klaim penyelesaian atau perhitungan hadiah.

### Beli nomor Telekos dan top up saldo

Bot menyediakan menu **Beli Nomor** atau perintah `/nomor` untuk memilih server, layanan, negara, dan harga dari katalog live Telekos. Sebelum membuat pesanan, bot mengambil penawaran/harga terbaru; setelah nomor diterima, harga Telekos ditambah margin Rp1.000 dipotong dari Saldo pengguna. OTP dapat diperiksa dari pesanan, dan pesanan yang memenuhi syarat dapat dibatalkan untuk mengembalikan Saldo.

Top up Saldo dilakukan lewat QRIS Midtrans (`/saldo`) dengan pilihan Rp3.000, Rp5.000, Rp10.000, atau nominal lain. Saldo internal bot ini dapat dipakai untuk membeli nomor maupun Premium; pembelian Premium juga tetap tersedia melalui QRIS. Operator bot perlu menjaga saldo akun Telekos cukup untuk menutup pesanan. Integrasi memakai API v1 `https://telekos.id/v1`, autentikasi Bearer, katalog `/servers`, `/apps`, `/countries`, `/prices`, dan pengelolaan pesanan `/orders`. Pembelian menggunakan `offer_id` dan kunci idempotensi. Pembatalan mengikuti status `can_cancel` dari Telekos. Top up QRIS mengisi Saldo internal bot, bukan saldo akun Telekos.

Pengguna dapat membuka **Undang teman** dari halaman utama atau `/invite`. Tautan undangan memberi Saldo Rp200 kepada teman baru saat pertama kali membuka bot. Pengundang mendapat komisi Saldo sebesar 1% dari setiap pembelian nomor teman yang berhasil diproses. Bonus pendaftaran dan komisi dicatat sekali agar pengulangan `/start` atau pemrosesan order ulang tidak menggandakan Saldo.

Pengumuman transaksi dikirim ke channel Telegram melalui `NUMBER_PURCHASE_CHANNEL_ID`. Untuk mewajibkan langganan, channel transaksi saat ini adalah `@lunafiletrx`; bot memeriksa keanggotaan sebelum memproses perintah, pesan, atau tombol, lalu meminta pengguna bergabung dan menekan tombol verifikasi jika belum menjadi anggota. Bot harus menjadi admin channel agar pemeriksaan keanggotaan berfungsi. Tambahkan bot sebagai admin dengan izin mengirim pesan. Setiap pembelian nomor mengirim layanan, negara, server, nomor yang disamarkan, dan waktu WIB, lalu menyertakan tombol **Beli Nomor** yang membuka bot melalui `/start beli_nomor`. Margin nomor dihitung dari harga dasar Telekos: Rp1.000 sampai Rp10.000, Rp2.000 di atas Rp10.000 sampai Rp20.000, Rp3.000 di atas Rp20.000 sebelum Rp30.000, Rp4.500 mulai Rp30.000 sebelum Rp50.000, Rp6.000 Rp50.000–Rp100.000, Rp10.000 di atas Rp100.000 sampai Rp200.000, lalu Rp25.000 di atas Rp200.000. Pembelian Premium melalui QRIS atau Saldo, pemberian Premium manual oleh admin, penukaran kode redeem, dan gift Premium baru juga diumumkan ke channel.

Setel `TELEKOS_API_KEY` dari Profile Telekos. Base URL default `https://telekos.id/v1`; `TELEKOS_API_BASE` dapat dipakai untuk mengganti host jika diperlukan. API key hanya digunakan di server dan jangan dikirim ke chat atau commit ke Git.

### Webhook OTP Telekos

Bot menerima event Telekos pada `POST /webhooks/telekos` (port lokal `8788`). `TELEKOS_WEBHOOK_SECRET` disimpan di `.env`; bot memverifikasi HMAC-SHA256 dari timestamp dan body mentah, menolak timestamp lebih dari lima menit, serta mengabaikan delivery ID duplikat. Event OTP dikirim ke chat Telegram pemesan. Event pembatalan atau kedaluwarsa memperbarui status dan mengembalikan saldo internal.

Listener secara default hanya bind ke `127.0.0.1`. Agar Telekos dapat menghubunginya, arahkan URL HTTPS publik dari reverse proxy atau tunnel tepercaya ke `http://127.0.0.1:8788/webhooks/telekos`, lalu daftarkan URL HTTPS tersebut pada pengaturan Webhooks di Profile Telekos. Secret webhook hanya disimpan di server; jangan memasukkannya ke URL, chat, atau Git.

Pembayaran QRIS memakai Midtrans yang sama dengan Premium. Isi `MIDTRANS_SERVER_KEY` dan `MIDTRANS_QRIS_ACQUIRER` (`gopay` atau acquirer QRIS lain yang diaktifkan pada akun), dan set `MIDTRANS_IS_PRODUCTION=false` untuk Sandbox. Uji transaksi Sandbox terlebih dahulu; untuk transaksi nyata isi Server Key Production dan ubah `MIDTRANS_IS_PRODUCTION=true`. Core API Production harus diaktifkan pada akun Midtrans. Jangan kirim atau commit Server Key.

Pengguna membuka `/paket`, memilih durasi 1 hari (Rp3.000), 5 hari (Rp8.000), 7 hari (Rp10.000), 15 hari (Rp15.000), 25 hari (Rp23.000), atau 30 hari (Rp28.000), lalu memilih pembayaran dengan Saldo atau QRIS. Pembelian dengan Saldo tersedia jika saldonya mencukupi. Pembayaran QRIS mengaktifkan Premium setelah status settlement Midtrans diverifikasi. Pembelian saat Premium masih aktif menambahkan masa aktif baru ke sisa masa aktif. Jika bot sedang berhenti ketika pembayaran QRIS selesai, tekan tombol **Periksa status pembayaran** pada pesan QR setelah bot aktif lagi. Integrasi ini memakai polling status Midtrans sehingga server Termux tidak membutuhkan webhook publik.

Pengguna dapat membuat gift dengan `/gift <hari> [jumlah_pengguna]`; contoh `/gift 1 3` memberi Premium 1 hari kepada tiga orang. Durasi dan jumlah penerima masing-masing 1–1000. Harga dihitung dari kombinasi termurah paket Premium yang tersedia per penerima, dikalikan jumlah penerima, lalu dipotong dari Saldo. Bot menyiarkan tombol klaim di channel transaksi sampai kuota penerima habis. Setiap orang hanya dapat mengklaim satu kali per gift; bot memperbarui jumlah klaim di channel dan memberi tahu pemberi serta penerima secara otomatis. Gift tidak dapat diklaim lewat `/redeem` atau dari chat lain.

### Panel admin

Panel hanya mendengarkan di perangkat lokal (`127.0.0.1`) dan meminta Basic Auth dengan nama pengguna `admin`. Buka `http://127.0.0.1:8787` di browser perangkat yang menjalankan bot. Kata sandi acak dibuat di `.env`; lihat dengan `grep '^ADMIN_PASSWORD=' .env`. Untuk menggantinya, edit nilai tersebut lalu mulai ulang bot.

Panel menampilkan pengguna Telegram, aktivitas, panggilan AI, pemakaian token, serta pendapatan kotor pembayaran Midtrans yang berhasil untuk pembelian Premium dan top up saldo. Ringkasan memisahkan kedua jenis pembayaran dan memuat transaksi terbaru; transaksi pending atau gagal tidak dihitung. Nilai memakai nominal pembayaran sebelum biaya Midtrans, bukan pencairan bersih. Token dicatat dari field `usage` pada respons AI. Jika penyedia API tidak mengirim field itu, pemakaian ditandai sebagai tidak dilaporkan dan tidak diestimasi. Database lokal `admin_stats.sqlite3` menyimpan statistik dan riwayat pembayaran, bukan isi file atau pesan.

### Menjalankan terus di Termux

Pengelola proses `server.sh` menjalankan bot di latar, memulai ulang jika bot keluar, dan memakai `termux-wake-lock` agar Android tidak menidurkan CPU.

```sh
./server.sh start
./server.sh status
./server.sh logs
./server.sh stop
```

Agar mulai otomatis setelah perangkat reboot, pasang aplikasi Termux:Boot dari sumber yang sama dengan Termux, lalu buat `~/.termux/boot/start-aif` berisi:

```sh
#!/data/data/com.termux/files/usr/bin/sh
/data/data/com.termux/files/home/aif/server.sh start
```

Beri izin eksekusi pada skrip boot (`chmod +x ~/.termux/boot/start-aif`). Android tetap dapat menghentikan aplikasi jika optimasi baterai aktif; izinkan Termux berjalan di latar belakang.

Jangan commit `.env`. API key dan token bot harus dijaga rahasia.

## Pemakaian

Kirim dokumen ke bot. Bot akan mengekstrak teks dan meminta ringkasan ke AI. Gunakan `/ask pertanyaan Anda` untuk pertanyaan lanjutan terhadap file terakhir yang dikirim pada chat tersebut.

Pengguna Gratis dapat memproses maksimal 5 file berhasil selama masa penggunaan akun; Premium dapat memproses file tanpa batas. Setelah masa Premium habis, akun kembali ke batas Gratis, termasuk jika sudah pernah memakai 5 file. Batas default ukuran file adalah 20 MB dan ekstraksi 100.000 karakter; keduanya dapat diubah lewat `MAX_FILE_MB` dan `MAX_EXTRACT_CHARS`. Kuota AI default adalah 5 panggilan per hari untuk Gratis dan 500 panggilan per bulan untuk Premium, dapat diubah lewat `FREE_DAILY_AI_LIMIT` dan `PREMIUM_MONTHLY_AI_LIMIT`. Paket Premium aktif sesuai durasi yang dibeli melalui Saldo atau QRIS Midtrans; admin juga dapat memberi Premium manual dari panel. Konten file dikirim ke Apinex untuk diproses. PDF scan yang hanya berisi gambar memerlukan OCR (belum disertakan). APK tidak didekompilasi; AndroidManifest biner tidak otomatis diterjemahkan.

### Video downloader

Pilih tombol **Video Downloader**, kirim tautan HTTPS, atau gunakan `/download <tautan>`. Unduhan memakai `yt-dlp` dan dibatasi 49 MB (`MAX_VIDEO_MB`) agar dapat dikirim melalui Telegram. Konten harus dapat diakses oleh akun yang dikonfigurasi dan extractor `yt-dlp` masih harus mendukung situs tersebut. Story Instagram yang memerlukan login membutuhkan file cookie Netscape yang sah dan dapat dibaca oleh bot; simpan di lokasi privat, lalu set `YTDLP_COOKIES_FILE=/lokasi/cookies.txt` di `.env`. Tanpa cookie, Story privat/tidak publik tidak dapat diunduh. Jangan membagikan cookie atau mengunduh konten tanpa izin.
