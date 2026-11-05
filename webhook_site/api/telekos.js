const { fail, forwardToTelegram, methodNotAllowed, parseJson, readRawBody, reply, verifyTelekos } = require('../lib/receiver');


async function handler(req, res) {
  if (req.method !== 'POST') return methodNotAllowed(req, res);
  const secret = process.env.TELEKOS_WEBHOOK_SECRET;
  if (!secret) return reply(res, 503, { error: 'TELEKOS_WEBHOOK_SECRET is not configured' });
  try {
    const raw = await readRawBody(req);
    if (!verifyTelekos(raw, req.headers['x-telekos-signature'], secret)) {
      return reply(res, 401, { error: 'Invalid or expired Telekos signature' });
    }
    const deliveryId = String(req.headers['x-telekos-delivery'] || '').trim();
    if (!deliveryId || deliveryId.length > 200) return reply(res, 400, { error: 'Missing or invalid Telekos delivery ID' });
    const event = parseJson(raw);
    await forwardToTelegram('Telekos', event, deliveryId);
    return reply(res, 200, { ok: true });
  } catch (error) { return fail(res, error); }
};

module.exports = handler;
module.exports.config = { api: { bodyParser: false } };
