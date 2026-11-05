const crypto = require('node:crypto');

const MAX_BODY_BYTES = 1024 * 1024;
const TELEGRAM_TEXT_LIMIT = 3900;

function reply(res, status, body = '') {
  res.statusCode = status;
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (body) res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(body ? JSON.stringify(body) : '');
}

function methodNotAllowed(req, res) {
  res.setHeader('Allow', 'POST');
  reply(res, 405, { error: 'Method not allowed' });
}

async function readRawBody(req) {
  const declared = Number(req.headers['content-length']);
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
    const error = new Error('Payload too large'); error.statusCode = 413; throw error;
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) {
      const error = new Error('Payload too large'); error.statusCode = 413; throw error;
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

function parseJson(raw) {
  let event;
  try { event = JSON.parse(raw.toString('utf8')); }
  catch { const error = new Error('Request body must be valid JSON'); error.statusCode = 400; throw error; }
  if (!event || typeof event !== 'object' || Array.isArray(event)) {
    const error = new Error('Request body must be a JSON object'); error.statusCode = 400; throw error;
  }
  return event;
}

function safeEqual(left, right) {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function hasApiKey(req, configuredKey) {
  const auth = req.headers.authorization || '';
  const bearer = auth.match(/^Bearer\s+(.+)$/i)?.[1] || '';
  const custom = req.headers['x-webhook-secret'] || '';
  return safeEqual(bearer, configuredKey) || safeEqual(custom, configuredKey);
}

function verifyTelekos(raw, signature, secret) {
  const timestampMatch = String(signature || '').match(/(?:^|,)\s*t=(\d+)(?:,|$)/);
  const digestMatch = String(signature || '').match(/(?:^|,)\s*v1=([0-9a-f]{64})(?:,|$)/i);
  if (!timestampMatch || !digestMatch) return false;
  const timestamp = Number(timestampMatch[1]);
  if (!Number.isSafeInteger(timestamp) || Math.abs(Date.now() / 1000 - timestamp) > 300) return false;
  const expected = crypto.createHmac('sha256', secret)
    .update(timestampMatch[1], 'ascii').update('.').update(raw).digest('hex');
  return safeEqual(expected.toLowerCase(), digestMatch[1].toLowerCase());
}

async function forwardToTelegram(source, event, deliveryId = '') {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) {
    const error = new Error('Telegram is not configured'); error.statusCode = 503; throw error;
  }
  const header = [`Webhook masuk: ${source}`];
  if (event.type) header.push(`Tipe: ${String(event.type).slice(0, 100)}`);
  if (deliveryId) header.push(`Delivery: ${deliveryId.slice(0, 150)}`);
  let text = `${header.join('\n')}\n\n${JSON.stringify(event, null, 2)}`;
  if (text.length > TELEGRAM_TEXT_LIMIT) text = `${text.slice(0, TELEGRAM_TEXT_LIMIT - 24)}\n… (payload dipotong)`;
  const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  if (!response.ok) {
    const error = new Error('Telegram could not deliver the message'); error.statusCode = 502; throw error;
  }
}

function fail(res, error) {
  const status = error.statusCode || 500;
  if (status >= 500) console.error('Webhook receiver error:', error.message);
  reply(res, status, { error: status >= 500 ? 'Webhook could not be delivered' : error.message });
}

module.exports = { fail, forwardToTelegram, hasApiKey, methodNotAllowed, parseJson, readRawBody, reply, verifyTelekos };
