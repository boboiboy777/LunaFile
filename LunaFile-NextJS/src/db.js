import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const dbPath = process.env.ADMIN_DB_PATH || path.join(root, 'admin_stats.sqlite3');
export const db = new DatabaseSync(dbPath);
db.exec('PRAGMA journal_mode=WAL; PRAGMA busy_timeout=10000;');
db.exec(`
CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '',
 first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, starts INTEGER NOT NULL DEFAULT 0,
 messages INTEGER NOT NULL DEFAULT 0, files INTEGER NOT NULL DEFAULT 0,
 files_success INTEGER NOT NULL DEFAULT 0, files_failed INTEGER NOT NULL DEFAULT 0,
 ai_calls INTEGER NOT NULL DEFAULT 0, ai_failed INTEGER NOT NULL DEFAULT 0,
 input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
 total_tokens INTEGER NOT NULL DEFAULT 0, reported_token_calls INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ai_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
 model TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', input_tokens INTEGER NOT NULL DEFAULT 0,
 output_tokens INTEGER NOT NULL DEFAULT 0, total_tokens INTEGER NOT NULL DEFAULT 0,
 usage_reported INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS blocked_users(user_id INTEGER PRIMARY KEY, blocked_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS airdrop_tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,
 description TEXT NOT NULL,url TEXT NOT NULL,created_by INTEGER NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES('maintenance','0');
INSERT OR IGNORE INTO settings VALUES('number_purchase_visible','0');
CREATE TABLE IF NOT EXISTS monthly_usage(user_id INTEGER NOT NULL,month TEXT NOT NULL,calls INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,month));
CREATE TABLE IF NOT EXISTS daily_usage(user_id INTEGER NOT NULL,day TEXT NOT NULL,calls INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,day));
CREATE TABLE IF NOT EXISTS premium_users(user_id INTEGER PRIMARY KEY,expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS redeem_codes(code TEXT PRIMARY KEY,plan_days INTEGER NOT NULL,max_uses INTEGER NOT NULL,used_count INTEGER NOT NULL DEFAULT 0,created_by INTEGER NOT NULL,created_at TEXT NOT NULL,is_gift INTEGER NOT NULL DEFAULT 0,gift_amount_idr INTEGER NOT NULL DEFAULT 0,gift_status TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS redeem_claims(code TEXT NOT NULL,user_id INTEGER NOT NULL,redeemed_at TEXT NOT NULL,PRIMARY KEY(code,user_id));
CREATE TABLE IF NOT EXISTS payments(order_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,amount_idr INTEGER NOT NULL,plan_days INTEGER NOT NULL DEFAULT 30,purpose TEXT NOT NULL DEFAULT 'premium',status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,paid_at TEXT,channel_announced INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS number_wallets(user_id INTEGER PRIMARY KEY,balance_idr INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS number_orders(order_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,price_idr INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS telekos_webhook_deliveries(delivery_id TEXT PRIMARY KEY,received_at TEXT NOT NULL);
`);
function ensureColumn(table, name, definition) {
  const cols = db.prepare(`PRAGMA table_info(${table})`).all().map(x => x.name);
  if (!cols.includes(name)) db.exec(`ALTER TABLE ${table} ADD COLUMN ${name} ${definition}`);
}
ensureColumn('users', 'files_success', 'INTEGER NOT NULL DEFAULT 0');
ensureColumn('users', 'files_failed', 'INTEGER NOT NULL DEFAULT 0');
ensureColumn('payments', 'plan_days', 'INTEGER NOT NULL DEFAULT 30');
ensureColumn('payments', 'purpose', "TEXT NOT NULL DEFAULT 'premium'");
ensureColumn('payments', 'paid_at', 'TEXT');
ensureColumn('payments', 'channel_announced', 'INTEGER NOT NULL DEFAULT 0');
ensureColumn('redeem_codes', 'is_gift', 'INTEGER NOT NULL DEFAULT 0');
ensureColumn('redeem_codes', 'gift_amount_idr', 'INTEGER NOT NULL DEFAULT 0');
ensureColumn('redeem_codes', 'gift_status', "TEXT NOT NULL DEFAULT ''");
db.exec("UPDATE payments SET channel_announced=1 WHERE status='paid'");

const iso = () => new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00');
const nameOf = u => [u.first_name, u.last_name].filter(Boolean).join(' ');
export function recordEvent(user, event) {
  if (!user) return;
  const now = iso();
  db.prepare(`INSERT INTO users(user_id,username,display_name,first_seen,last_seen) VALUES(?,?,?,?,?)
    ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,display_name=excluded.display_name,last_seen=excluded.last_seen`)
    .run(user.id, user.username || '', nameOf(user), now, now);
  const field = { start: 'starts', message: 'messages', file: 'files' }[event];
  if (field) db.prepare(`UPDATE users SET ${field}=${field}+1 WHERE user_id=?`).run(user.id);
}
export function recordFileResult(user, success) {
  if (!user) return;
  db.prepare('UPDATE users SET files_success=files_success+?,files_failed=files_failed+? WHERE user_id=?')
    .run(Number(success), Number(!success), user.id);
}
export function beginAi(user, model) {
  if (!user) return null;
  const now = iso();
  db.prepare(`INSERT INTO users(user_id,username,display_name,first_seen,last_seen,ai_calls) VALUES(?,?,?,?,?,1)
   ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,display_name=excluded.display_name,last_seen=excluded.last_seen,ai_calls=users.ai_calls+1`)
    .run(user.id, user.username || '', nameOf(user), now, now);
  return Number(db.prepare('INSERT INTO ai_requests(user_id,created_at,model) VALUES(?,?,?)').run(user.id, now, model).lastInsertRowid);
}
export function finishAi(id, status, usage = {}) {
  if (!id) return;
  const row = db.prepare('SELECT user_id FROM ai_requests WHERE id=?').get(id);
  if (!row) return;
  const inp = Number(usage.prompt_tokens ?? usage.input_tokens ?? 0) || 0;
  const out = Number(usage.completion_tokens ?? usage.output_tokens ?? 0) || 0;
  const total = Number(usage.total_tokens ?? (inp + out)) || inp + out;
  const reported = ['prompt_tokens','input_tokens','completion_tokens','output_tokens','total_tokens'].some(k => k in usage);
  db.prepare('UPDATE ai_requests SET status=?,input_tokens=?,output_tokens=?,total_tokens=?,usage_reported=? WHERE id=?')
    .run(status, inp, out, total, Number(reported), id);
  db.prepare(`UPDATE users SET ai_failed=ai_failed+?,input_tokens=input_tokens+?,output_tokens=output_tokens+?,
    total_tokens=total_tokens+?,reported_token_calls=reported_token_calls+? WHERE user_id=?`)
    .run(Number(status !== 'ok'), inp, out, total, Number(reported), row.user_id);
}
export function quota(userId, freeLimit, premiumLimit, consume = false) {
  const now = new Date(), stamp = iso(), day = stamp.slice(0, 10), month = stamp.slice(0, 7);
  const premium = db.prepare('SELECT expires_at FROM premium_users WHERE user_id=?').get(userId);
  const active = Boolean(premium && premium.expires_at > stamp);
  const period = active ? month : day, table = active ? 'monthly_usage' : 'daily_usage';
  const col = active ? 'month' : 'day', limit = active ? premiumLimit : freeLimit;
  db.prepare(`INSERT OR IGNORE INTO ${table}(user_id,${col},calls) VALUES(?,?,0)`).run(userId, period);
  if (consume) db.prepare(`UPDATE ${table} SET calls=calls+1 WHERE user_id=? AND ${col}=? AND calls<?`).run(userId, period, limit);
  const used = Number(db.prepare(`SELECT calls FROM ${table} WHERE user_id=? AND ${col}=?`).get(userId, period).calls);
  return { ok: used < limit, used, limit, plan: active ? 'Premium' : 'Gratis', period: active ? 'bulan ini' : 'hari ini', expires_at: active ? premium.expires_at : null };
}
export function getUserPlan(userId, freeLimit, premiumLimit) {
  const q = quota(userId, freeLimit, premiumLimit, false);
  const premium = db.prepare('SELECT expires_at FROM premium_users WHERE user_id=?').get(userId);
  return { ...q, premium_expires_at: premium?.expires_at || null };
}
export const isBlocked = id => Boolean(db.prepare('SELECT 1 FROM blocked_users WHERE user_id=?').get(id));
export function setBlocked(id, blocked) {
  if (blocked) db.prepare('INSERT OR REPLACE INTO blocked_users VALUES(?,?)').run(id, iso());
  else db.prepare('DELETE FROM blocked_users WHERE user_id=?').run(id);
}
export function getFileCount(id) { return Number(db.prepare('SELECT files_success FROM users WHERE user_id=?').get(id)?.files_success || 0); }
export function numberBalance(id) { return Number(db.prepare('SELECT balance_idr FROM number_wallets WHERE user_id=?').get(id)?.balance_idr || 0); }
export function addWallet(id, amount) {
  db.prepare('INSERT INTO number_wallets(user_id,balance_idr) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET balance_idr=balance_idr+excluded.balance_idr').run(id, amount);
}
export function purchasePremiumWithWallet(userId, days, amount) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const balance = numberBalance(userId);
    if (balance < amount) { db.exec('ROLLBACK'); return { ok: false, balance }; }
    db.prepare('UPDATE number_wallets SET balance_idr=balance_idr-? WHERE user_id=?').run(amount, userId);
    const expiresAt = grantPremium(userId, days);
    db.exec('COMMIT');
    return { ok: true, balance: balance - amount, expires_at: expiresAt };
  } catch (e) { db.exec('ROLLBACK'); throw e; }
}
export function debitWallet(id, amount, order) {
  db.exec('BEGIN IMMEDIATE');
  try {
    if (numberBalance(id) < amount) { db.exec('ROLLBACK'); return false; }
    db.prepare('UPDATE number_wallets SET balance_idr=balance_idr-? WHERE user_id=?').run(amount, id);
    db.prepare('INSERT OR REPLACE INTO number_orders(order_id,user_id,price_idr,status,created_at) VALUES(?,?,?,?,?)').run(order.id, id, amount, order.status || 'waiting', iso());
    db.exec('COMMIT'); return true;
  } catch (e) { db.exec('ROLLBACK'); throw e; }
}
export function getOrderOwner(orderId) { return db.prepare('SELECT user_id FROM number_orders WHERE order_id=?').get(orderId)?.user_id ?? null; }
export function updateOrder(orderId, status) { db.prepare('UPDATE number_orders SET status=? WHERE order_id=?').run(status, orderId); }
export function refundOrder(orderId, userId) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const row = db.prepare("SELECT price_idr,status FROM number_orders WHERE order_id=? AND user_id=?").get(orderId,userId);
    if (!row || ['cancelled','expired','refunded'].includes(row.status)) { db.exec('ROLLBACK'); return false; }
    db.prepare('UPDATE number_wallets SET balance_idr=balance_idr+? WHERE user_id=?').run(row.price_idr,userId);
    db.prepare("UPDATE number_orders SET status='refunded' WHERE order_id=?").run(orderId);
    db.exec('COMMIT'); return true;
  } catch(e) { db.exec('ROLLBACK'); throw e; }
}
export function claimDelivery(id) {
  const r = db.prepare('INSERT OR IGNORE INTO telekos_webhook_deliveries(delivery_id,received_at) VALUES(?,?)').run(id,iso());
  return r.changes === 1;
}
export function releaseDelivery(id) { db.prepare('DELETE FROM telekos_webhook_deliveries WHERE delivery_id=?').run(id); }
export function createPayment(p) {
  db.prepare(`INSERT OR REPLACE INTO payments(order_id,user_id,amount_idr,plan_days,purpose,status,created_at,expires_at)
   VALUES(?,?,?,?,?,?,?,?)`).run(p.id,p.userId,p.amount,p.days,p.purpose,'pending',iso(),p.expiresAt);
}
export function getPayment(id) { return db.prepare('SELECT * FROM payments WHERE order_id=?').get(id); }
export function settlePayment(id) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const p = getPayment(id);
    if (!p || p.status === 'paid') { db.exec('ROLLBACK'); return false; }
    db.prepare("UPDATE payments SET status='paid',paid_at=? WHERE order_id=?").run(iso(),id);
    if (p.purpose === 'numbers_topup') addWallet(p.user_id,p.amount_idr);
    else grantPremium(p.user_id,p.plan_days);
    db.exec('COMMIT'); return true;
  } catch(e) { db.exec('ROLLBACK'); throw e; }
}
export function grantPremium(userId, days) {
  const now = new Date(), existing = db.prepare('SELECT expires_at FROM premium_users WHERE user_id=?').get(userId);
  const base = existing && existing.expires_at > iso() ? new Date(existing.expires_at) : now;
  base.setUTCDate(base.getUTCDate() + Number(days)); const expires = base.toISOString().replace(/\.\d{3}Z$/,'+00:00');
  db.prepare('INSERT INTO premium_users VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET expires_at=excluded.expires_at').run(userId,expires);
  return expires;
}
export function redeem(code,userId) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const c = db.prepare('SELECT * FROM redeem_codes WHERE code=?').get(code.toUpperCase());
    if (!c) { db.exec('ROLLBACK'); return ['invalid']; }
    if (c.is_gift) { db.exec('ROLLBACK'); return ['gift_channel',c.plan_days,c.used_count,c.max_uses]; }
    if (db.prepare('SELECT 1 FROM redeem_claims WHERE code=? AND user_id=?').get(code.toUpperCase(),userId)) { db.exec('ROLLBACK'); return ['already_used',c.plan_days,c.used_count,c.max_uses]; }
    if (c.used_count >= c.max_uses) { db.exec('ROLLBACK'); return ['exhausted',c.plan_days,c.used_count,c.max_uses]; }
    db.prepare('INSERT INTO redeem_claims VALUES(?,?,?)').run(code.toUpperCase(),userId,iso());
    db.prepare('UPDATE redeem_codes SET used_count=used_count+1 WHERE code=?').run(code.toUpperCase());
    grantPremium(userId,c.plan_days); db.exec('COMMIT'); return ['ok',c.plan_days,c.used_count+1,c.max_uses];
  } catch(e) { db.exec('ROLLBACK'); throw e; }
}
export function setting(key, fallback = '') { return db.prepare('SELECT value FROM settings WHERE key=?').get(key)?.value ?? fallback; }
export function setSetting(key,value) { db.prepare('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(key,String(value)); }
export function addAirdrop(title,description,url,admin) { return Number(db.prepare('INSERT INTO airdrop_tasks(title,description,url,created_by,created_at) VALUES(?,?,?,?,?)').run(title,description,url,admin,iso()).lastInsertRowid); }
export function listAirdrops(limit=10,offset=0) { return db.prepare('SELECT * FROM airdrop_tasks ORDER BY id DESC LIMIT ? OFFSET ?').all(limit,offset); }
export function adminStats() {
  const totals=db.prepare('SELECT COUNT(*) users,COALESCE(SUM(ai_calls),0) calls,COALESCE(SUM(ai_failed),0) failed,COALESCE(SUM(total_tokens),0) tokens FROM users').get();
  const users=db.prepare('SELECT user_id,username,display_name,last_seen,files_success,ai_calls FROM users ORDER BY last_seen DESC LIMIT 200').all();
  const requests=db.prepare('SELECT r.*,u.username FROM ai_requests r LEFT JOIN users u USING(user_id) ORDER BY r.id DESC LIMIT 30').all();
  return {totals,users,requests};
}
export function adminUsers(offset=0) { return db.prepare('SELECT * FROM users ORDER BY last_seen DESC LIMIT 20 OFFSET ?').all(offset); }
export function deleteUser(id) { for (const t of ['users','ai_requests','daily_usage','monthly_usage','premium_users','number_wallets','number_orders']) db.prepare(`DELETE FROM ${t} WHERE user_id=?`).run(id); }
export function recentUsers() { return db.prepare('SELECT user_id,username,display_name FROM users ORDER BY last_seen DESC LIMIT 8').all(); }
export function createRedeem(code,days,max,admin) { db.prepare('INSERT INTO redeem_codes(code,plan_days,max_uses,created_by,created_at) VALUES(?,?,?,?,?)').run(code.toUpperCase(),days,max,admin,iso()); }
export function claimAnnouncement(orderId) { return db.prepare("UPDATE payments SET channel_announced=1 WHERE order_id=? AND channel_announced=0").run(orderId).changes===1; }
export function addPaymentNumberOrder(orderId,userId,price,status='waiting') { db.prepare('INSERT OR REPLACE INTO number_orders VALUES(?,?,?,?,?)').run(orderId,userId,price,status,iso()); }
export function listRedeems() { return db.prepare('SELECT * FROM redeem_codes WHERE is_gift=0 ORDER BY created_at DESC LIMIT 10').all(); }
export function createPremiumGift(code,gifterId,days,users,amount) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const balance=numberBalance(gifterId);
    if(balance<amount){db.exec('ROLLBACK');return{ok:false,balance};}
    db.prepare('UPDATE number_wallets SET balance_idr=balance_idr-? WHERE user_id=?').run(amount,gifterId);
    db.prepare("INSERT INTO redeem_codes(code,plan_days,max_uses,created_by,created_at,is_gift,gift_amount_idr,gift_status) VALUES(?,?,?,?,?,1,?,'publishing')")
      .run(code.toUpperCase(),days,users,gifterId,iso(),amount);
    db.exec('COMMIT');return{ok:true,balance:balance-amount};
  } catch(e) {db.exec('ROLLBACK');throw e;}
}
export function activatePremiumGift(code) { return db.prepare("UPDATE redeem_codes SET gift_status='active' WHERE code=? AND is_gift=1 AND gift_status='publishing'").run(code.toUpperCase()).changes===1; }
export function cancelPremiumGift(code) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const gift=db.prepare("SELECT created_by,gift_amount_idr FROM redeem_codes WHERE code=? AND is_gift=1 AND gift_status='publishing'").get(code.toUpperCase());
    if(!gift){db.exec('ROLLBACK');return false;}
    db.prepare("UPDATE redeem_codes SET gift_status='cancelled' WHERE code=?").run(code.toUpperCase());
    db.prepare('UPDATE number_wallets SET balance_idr=balance_idr+? WHERE user_id=?').run(gift.gift_amount_idr,gift.created_by);
    db.exec('COMMIT');return true;
  } catch(e) {db.exec('ROLLBACK');throw e;}
}
export function claimPremiumGift(code,userId) {
  db.exec('BEGIN IMMEDIATE');
  try {
    const gift=db.prepare('SELECT * FROM redeem_codes WHERE code=? AND is_gift=1').get(code.toUpperCase());
    if(!gift){db.exec('ROLLBACK');return{state:'invalid'};}
    if(gift.created_by===userId){db.exec('ROLLBACK');return{state:'self_claim'};}
    if(gift.gift_status==='claimed'||gift.used_count>=gift.max_uses){db.exec('ROLLBACK');return{state:'claimed'};}
    if(gift.gift_status!=='active'){db.exec('ROLLBACK');return{state:'unavailable'};}
    if(db.prepare('SELECT 1 FROM redeem_claims WHERE code=? AND user_id=?').get(code.toUpperCase(),userId)){db.exec('ROLLBACK');return{state:'already_claimed'};}
    db.prepare('INSERT INTO redeem_claims VALUES(?,?,?)').run(code.toUpperCase(),userId,iso());
    const usedCount=Number(gift.used_count)+1,maxUses=Number(gift.max_uses),status=usedCount>=maxUses?'claimed':'active';
    db.prepare('UPDATE redeem_codes SET used_count=?,gift_status=? WHERE code=?').run(usedCount,status,code.toUpperCase());
    const expiresAt=grantPremium(userId,gift.plan_days);
    db.exec('COMMIT');return{state:'ok',days:gift.plan_days,gifterId:gift.created_by,usedCount,maxUses,remaining:maxUses-usedCount,expires_at:expiresAt};
  } catch(e) {db.exec('ROLLBACK');throw e;}
}
export function deleteAirdrop(id) { return db.prepare('DELETE FROM airdrop_tasks WHERE id=?').run(id).changes>0; }
export function getAirdrop(id) { return db.prepare('SELECT * FROM airdrop_tasks WHERE id=?').get(id); }
export function getAdminUser(id) { return db.prepare('SELECT * FROM users WHERE user_id=?').get(id); }
export function revokePremium(id) { db.prepare('DELETE FROM premium_users WHERE user_id=?').run(id); }
export function getNumberVisibility() { return setting('number_purchase_visible','0')==='1'; }
export function getMaintenance() { return setting('maintenance','0')==='1'; }
export function setStatus(userId, status) { db.prepare('UPDATE number_orders SET status=? WHERE user_id=?').run(status,userId); }
export function allUserIds() { return db.prepare('SELECT user_id FROM users ORDER BY user_id').all().map(x=>x.user_id); }
export function removeAirdrop(id) { return deleteAirdrop(id); }
