import crypto from 'node:crypto';
import { handleTelegramUpdate } from '../../../src/bot.js';
export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function POST(request){
 const secret=process.env.TELEGRAM_WEBHOOK_SECRET||'';
 const supplied=request.headers.get('x-telegram-bot-api-secret-token')||'';
 const a=Buffer.from(secret),b=Buffer.from(supplied);
 if(!secret||a.length!==b.length||!crypto.timingSafeEqual(a,b))return new Response('Unauthorized',{status:401});
 try{const update=await request.json();await handleTelegramUpdate(update);return Response.json({ok:true});}
 catch(error){console.error('Telegram webhook failed:',error.message);return Response.json({ok:false},{status:500});}
}
