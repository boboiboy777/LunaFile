import crypto from 'node:crypto';
import { adminStats } from '../../../src/db.js';
export const runtime='nodejs';
export const dynamic='force-dynamic';
function authorized(header){const expected=process.env.ADMIN_PASSWORD||'';if(!expected||!header?.startsWith('Basic '))return false;let decoded;try{decoded=Buffer.from(header.slice(6),'base64').toString('utf8')}catch{return false;}const i=decoded.indexOf(':');if(i<0||decoded.slice(0,i)!=='admin')return false;const got=Buffer.from(decoded.slice(i+1)),want=Buffer.from(expected);return got.length===want.length&&cryptoSafeEqual(got,want);}
function cryptoSafeEqual(a,b){return a.length===b.length&&require('node:crypto').timingSafeEqual(a,b);}
export async function GET(request){if(!authorized(request.headers.get('authorization')))return Response.json({error:'unauthorized'},{status:401,headers:{'www-authenticate':'Basic realm="LunaFile Admin"','cache-control':'no-store'}});return Response.json(adminStats(),{headers:{'cache-control':'no-store'}});}
