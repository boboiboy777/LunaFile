const { fail, forwardToTelegram, hasApiKey, methodNotAllowed, parseJson, readRawBody, reply } = require('../lib/receiver');

async function handler(req, res) {
  if (req.method !== 'POST') return methodNotAllowed(req, res);
  const key = process.env.WEBHOOK_API_KEY;
  if (!key) return reply(res, 503, { error: 'WEBHOOK_API_KEY is not configured' });
  if (!hasApiKey(req, key)) return reply(res, 401, { error: 'Invalid webhook key' });
  try {
    const event = parseJson(await readRawBody(req));
    await forwardToTelegram('generic', event);
    return reply(res, 200, { ok: true });
  } catch (error) { return fail(res, error); }
};

module.exports = handler;
module.exports.config = { api: { bodyParser: false } };
