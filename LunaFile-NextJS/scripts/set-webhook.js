import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const dir=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const envPath=path.join(dir,'.env');if(fs.existsSync(envPath))for(const line of fs.readFileSync(envPath,'utf8').split(/\r?\n/)){const m=line.match(/^\s*([\w]+)\s*=\s*(.*)\s*$/);if(m&&!process.env[m[1]])process.env[m[1]]=m[2].replace(/^(['"])(.*)\1$/,'$2');}
const token=process.env.TELEGRAM_BOT_TOKEN,base=(process.env.WEBHOOK_BASE_URL||'').replace(/\/$/,'');let secret=process.env.TELEGRAM_WEBHOOK_SECRET;
if(!token||!base)throw new Error('Isi TELEGRAM_BOT_TOKEN dan WEBHOOK_BASE_URL di .env.');
if(!secret)throw new Error('Buat TELEGRAM_WEBHOOK_SECRET acak (1–256 karakter alfanumerik, _ atau -), simpan di .env lalu ulangi.');
if(!/^[A-Za-z0-9_-]{1,256}$/.test(secret))throw new Error('TELEGRAM_WEBHOOK_SECRET hanya boleh memakai huruf, angka, _ dan -.');
const res=await fetch(`https://api.telegram.org/bot${token}/setWebhook`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({url:`${base}/api/telegram`,secret_token:secret,allowed_updates:['message','callback_query'],drop_pending_updates:false})});const data=await res.json();if(!res.ok||!data.ok)throw new Error(data.description||'setWebhook gagal');console.log('Webhook Telegram terpasang:',`${base}/api/telegram`);
