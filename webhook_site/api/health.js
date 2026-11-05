module.exports = function handler(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET'); res.statusCode = 405; return res.end();
  }
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.statusCode = 200;
  res.end(JSON.stringify({
    ok: true,
    telegramConfigured: Boolean(process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID),
    genericWebhookConfigured: Boolean(process.env.WEBHOOK_API_KEY),
    telekosConfigured: Boolean(process.env.TELEKOS_WEBHOOK_SECRET),
  }));
};
