// brand9 server (Node.js): static files + user accounts + SQLite-backed progress sync.
//
// Zero third-party dependencies (node:http + node:sqlite + node:crypto + node:tls).
// Drop-in equivalent of the former server.py. Endpoints:
//   POST /api/send_code          {email} -> 6-digit verification email
//   POST /api/register           {username, password, email, code}
//   POST /api/login              {username, password} -> {token}
//   POST /api/logout             (Bearer) -> invalidates token
//   GET  /api/me                 (Bearer) -> {username}
//   GET  /api/me/link            (Bearer) -> {open, token} 免密直达链接状态
//   POST /api/me/link/gen        (Bearer) -> 生成/重置本人直达链接 token
//   POST /api/login/link         {token}  -> 用直达链接换取会话 (登录免密)
//   GET  /api/state              (Bearer) -> {key: {value, updated_at}}
//   POST /api/state/sync         (Bearer) {entries:[{key, value, updated_at}]}
//   POST /api/state/clear        (Bearer) -> wipe user state (keep account)
//   Admin: /api/admin/me|accounts|accounts/:id|accounts/:id/reset|smtp|keys
//          /api/admin/accounts/:id/link (GET 读取 / PUT {open} 开放可见性)
//   Membership: GET /api/membership/me, POST /api/membership/convert,
//               POST /api/membership/activate {code}
//   GET  /api/scoreboard         (Bearer) -> all users' gold fragments (leaderboard)
//
// Auth: login issues a bearer token kept in memory (expires after 30 days).
// Passwords: PBKDF2-HMAC-SHA256 with per-user random salt (120k iterations).
// State rows are upserted per key; older timestamps never overwrite newer ones.
//
// Email verification (anti mass-registration):
//   code = 6 digits, valid for 5 minutes, resend allowed after 60s cooldown;
//   a resend invalidates the previous code. SMTP settings come from the
//   dw-shop .env / process env, or the admin-configured kv table.

'use strict';

const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const tls = require('node:tls');
const { DatabaseSync } = require('node:sqlite');

const PORT = parseInt(process.env.BRAND9_PORT || '8996', 10);
const DIR = __dirname;
const DB_PATH = path.join(DIR, 'brand9.db');

const TOKEN_TTL = 30 * 24 * 3600;   // 30 days
const PBKDF2_ITER = 120_000;
const EMAIL_RE = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;
const CODE_TTL = 300;               // verification code valid for 5 minutes
const RESEND_INTERVAL = 60;         // min seconds between two sends to the same address

// ----------------------------------------------------- env (shared creds)
function readDotEnv(filePath) {
  const out = {};
  try {
    const txt = fs.readFileSync(filePath, 'utf8');
    for (const raw of txt.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const i = line.indexOf('=');
      const k = line.slice(0, i).trim();
      let v = line.slice(i + 1).trim();
      v = v.replace(/^["']/, '').replace(/["']$/, '');
      out[k] = v;
    }
  } catch (_) { /* no such env file */ }
  return out;
}

const LOCAL_ENV = readDotEnv(path.join(DIR, '.env'));
const DWSHOP_ENV = readDotEnv(path.join(DIR, '..', 'fun', 'dw-shop', '.env'));

// Resend API (verification emails). Falls back to SMTP below when unset.
const RESEND_API_KEY = process.env.RESEND_API_KEY || LOCAL_ENV.RESEND_API_KEY || DWSHOP_ENV.RESEND_API_KEY || '';
const RESEND_ENDPOINT = process.env.RESEND_ENDPOINT || LOCAL_ENV.RESEND_ENDPOINT || DWSHOP_ENV.RESEND_ENDPOINT || 'https://api.resend.com/emails';
const MAIL_FROM = process.env.BRAND9_MAIL_FROM || LOCAL_ENV.BRAND9_MAIL_FROM || DWSHOP_ENV.BRAND9_MAIL_FROM || 'onboarding@resend.dev';

const SMTP_HOST = process.env.DW_SHOP_SMTP_HOST || DWSHOP_ENV.DW_SHOP_SMTP_HOST || 'smtp.qq.com';
const SMTP_PORT = parseInt(process.env.DW_SHOP_SMTP_PORT || DWSHOP_ENV.DW_SHOP_SMTP_PORT || '465', 10);

// db handle (single synchronous connection, created below)
let db;

function getSmtpCreds() {
  // Precedence: process env / dw-shop .env, then the admin-configured QQ
  // email + authorization key stored in the `kv` table.
  let user = process.env.DW_SHOP_SMTP_USER || DWSHOP_ENV.DW_SHOP_SMTP_USER || '';
  let pw = process.env.DW_SHOP_SMTP_PASSWORD || DWSHOP_ENV.DW_SHOP_SMTP_PASSWORD || '';
  if (user && pw) return { user, pass: pw };
  try {
    const u = db.prepare("SELECT v FROM kv WHERE k='smtp_user'").get();
    const p = db.prepare("SELECT v FROM kv WHERE k='smtp_pass'").get();
    if (u && u.v && p && p.v) return { user: u.v, pass: p.v };
  } catch (_) { /* ignore */ }
  return { user: '', pass: '' };
}

function smtpSend({ host, port, user, pass, from, to, subject, html }) {
  // Minimal SMTP client over TLS (works with QQ SMTP on 465).
  return new Promise((resolve, reject) => {
    let socket;
    let buffer = '';
    let current = null;
    let finished = false;

    const done = (err) => {
      if (finished) return;
      finished = true;
      try { socket.destroy(); } catch (_) { /* ignore */ }
      if (err) reject(err); else resolve();
    };

    const step = (codes, cmd, next) => {
      current = { codes, next };
      if (cmd != null) socket.write(cmd + '\r\n');
    };

    const onLine = (line) => {
      if (line.length < 3) return;
      const code = parseInt(line.slice(0, 3), 10);
      if (line[3] === '-') return; // multiline continuation, wait for final
      if (!current) return;
      if (current.codes.includes(code)) {
        const n = current.next;
        current = null;
        n();
      } else {
        done(new Error('SMTP 响应异常: ' + line));
      }
    };

    const onData = (chunk) => {
      buffer += chunk.toString('utf8');
      let i;
      while ((i = buffer.indexOf('\r\n')) !== -1) {
        const line = buffer.slice(0, i);
        buffer = buffer.slice(i + 2);
        onLine(line);
      }
    };

    socket = tls.connect({ host, port, rejectUnauthorized: false }, () => { /* greeting handled below */ });
    socket.on('data', onData);
    socket.setTimeout(15000, () => done(new Error('SMTP 连接超时')));
    socket.on('error', (e) => done(e));

    // greeting (220) -> EHLO -> AUTH LOGIN -> user -> pass -> MAIL FROM -> RCPT TO -> DATA -> body -> QUIT
    step([220], null, () => {
      step([250], 'EHLO brand9-node', () => {
        step([334], 'AUTH LOGIN', () => {
          step([334], Buffer.from(user).toString('base64'), () => {
            step([235], Buffer.from(pass).toString('base64'), () => {
              step([250], `MAIL FROM:<${from}>`, () => {
                step([250], `RCPT TO:<${to}>`, () => {
                  step([354], 'DATA', () => {
                    const subj = '=?UTF-8?B?' + Buffer.from(subject, 'utf8').toString('base64') + '?=';
                    let msg = `From: ${from}\r\nTo: ${to}\r\nSubject: ${subj}\r\n` +
                      'MIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n' + html;
                    msg = msg.replace(/\r?\n/g, '\r\n').replace(/^\./gm, '..');
                    socket.write(msg + '\r\n.\r\n');
                    step([250], null, () => {
                      step([221], 'QUIT', () => done(null));
                    });
                  });
                });
              });
            });
          });
        });
      });
    });
  });
}

async function resendSend({ from, to, subject, html }) {
  const payload = JSON.stringify({ from, to: [to], subject, html });
  const res = await fetch(RESEND_ENDPOINT, {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + RESEND_API_KEY,
      'Content-Type': 'application/json',
      'User-Agent': 'Mozilla/5.0 (brand9-server)',
    },
    body: payload,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status} ${detail}`);
  }
}

async function sendVerificationEmail(email, code) {
  const bodyHtml = `<div style="max-width:520px;margin:0 auto;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2328;background:#f6f7f9;padding:20px;">
  <div style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);">
    <div style="background:linear-gradient(135deg,#1a1f2e,#2d3550);color:#fff;padding:22px 26px;">
      <div style="font-size:19px;font-weight:700;">brand9<span style="color:#ffbca8;">·</span>雅思口语</div>
      <div style="font-size:13px;opacity:.85;margin-top:2px;">邮箱注册验证码</div>
    </div>
    <div style="padding:24px 26px;">
      <p style="margin:0 0 16px;font-size:14px;">你的注册验证码是：</p>
      <div style="margin:0 auto 18px;padding:20px;border:2px dashed #2d3550;border-radius:14px;text-align:center;">
        <div style="font-size:30px;font-weight:800;letter-spacing:6px;color:#1a1f2e;">${code}</div>
      </div>
      <p style="margin:0;font-size:13px;color:#6b7280;">验证码 <b>5 分钟内</b>有效。如果 1 分钟内重复发送，请以最新一封邮件为准。如非本人操作，请忽略本邮件。</p>
    </div>
    <div style="background:#fafbfc;padding:14px 26px;font-size:12px;color:#9ca3af;text-align:center;">
      brand9 · 雅思口语练习
    </div>
  </div>
</div>`;
  if (RESEND_API_KEY) {
    try {
      await resendSend({ from: MAIL_FROM, to: email, subject: '【brand9】邮箱注册验证码', html: bodyHtml });
      return null;
    } catch (e) {
      return '邮件发送失败: ' + (e && e.message ? e.message : String(e));
    }
  }
  const creds = getSmtpCreds();
  if (!creds.user || !creds.pass) return '邮件发送失败: Resend 未配置且 SMTP 未配置（请填 RESEND_API_KEY 或管理员后台的 QQ 邮箱授权码）';
  try {
    await smtpSend({
      host: SMTP_HOST, port: SMTP_PORT,
      user: creds.user, pass: creds.pass,
      from: creds.user, to: email,
      subject: '【brand9】邮箱注册验证码',
      html: bodyHtml,
    });
    return null;
  } catch (e) {
    return '邮件发送失败: ' + e.message;
  }
}

// in-memory token store: token -> {user_id, expires}
const TOKENS = new Map();

// ---------------------------------------------------------------- database
function initDb() {
  db = new DatabaseSync(DB_PATH);
  db.exec(`CREATE TABLE IF NOT EXISTS users (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      username   TEXT UNIQUE NOT NULL,
      pass_salt  TEXT NOT NULL,
      pass_hash  TEXT NOT NULL,
      created_at TEXT NOT NULL,
      email      TEXT,
      role       TEXT NOT NULL DEFAULT 'user',
      parent_id  INTEGER,
      note       TEXT
    );
    CREATE TABLE IF NOT EXISTS user_state (
      user_id    INTEGER NOT NULL,
      key        TEXT NOT NULL,
      value      TEXT NOT NULL,
      updated_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, key),
      FOREIGN KEY (user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS email_codes (
      email      TEXT PRIMARY KEY,
      code       TEXT NOT NULL,
      sent_at    INTEGER NOT NULL,
      expires_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS vip_keys (
      code       TEXT PRIMARY KEY,
      type       TEXT NOT NULL,                    -- '7d' | '14d'
      used_by    INTEGER,
      used_at    INTEGER,
      created_by INTEGER,
      created_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS membership (
      user_id        INTEGER PRIMARY KEY,
      key_type       TEXT,                         -- 激活的密钥类型 '7d' | '14d'
      key_start      INTEGER,
      key_expires    INTEGER,
      gold           INTEGER NOT NULL DEFAULT 0,   -- 金色碎片（= 金色积分）
      yd_level       INTEGER NOT NULL DEFAULT 0,   -- 黄钻等级（首次兑换=1级，再兑换+1级）
      grace_days     INTEGER NOT NULL DEFAULT 0,   -- 金碎片耗尽后黄钻可保留的天数
      last_day_reward INTEGER NOT NULL DEFAULT 0,  -- 今日已发放的练满奖励快照（防重复补算）
      last_status_day TEXT,                        -- 已结算的最后一天 (yyyy-mm-dd)
      updated_at     INTEGER
    );
  `);
  const cols = db.prepare('PRAGMA table_info(users)').all().map((r) => r.name);
  if (!cols.includes('email')) db.exec('ALTER TABLE users ADD COLUMN email TEXT');
  if (!cols.includes('role')) db.exec("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'");
  if (!cols.includes('parent_id')) db.exec('ALTER TABLE users ADD COLUMN parent_id INTEGER');
  if (!cols.includes('note')) db.exec('ALTER TABLE users ADD COLUMN note TEXT');
  if (!cols.includes('nickname')) db.exec('ALTER TABLE users ADD COLUMN nickname TEXT');
  if (!cols.includes('uuid')) db.exec('ALTER TABLE users ADD COLUMN uuid TEXT');
  if (!cols.includes('link_open')) db.exec("ALTER TABLE users ADD COLUMN link_open INTEGER NOT NULL DEFAULT 0");
  if (!cols.includes('login_token')) db.exec('ALTER TABLE users ADD COLUMN login_token TEXT');
  db.exec('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)');
  db.exec('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login_token ON users(login_token)');
  db.exec('CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);');
  // membership 列迁移（旧库可能没有 grace_days / 仍有 streak 旧列，保留不影响）
  const memCols = db.prepare('PRAGMA table_info(membership)').all().map((r) => r.name);
  if (!memCols.includes('grace_days')) db.exec('ALTER TABLE membership ADD COLUMN grace_days INTEGER NOT NULL DEFAULT 0');
  if (!memCols.includes('last_day_reward')) db.exec('ALTER TABLE membership ADD COLUMN last_day_reward INTEGER NOT NULL DEFAULT 0');
  console.log(`[db] ready at ${DB_PATH}`);
}

// ------------------------------------------------------------------- crypto
function hashPassword(password, saltHex) {
  return crypto.pbkdf2Sync(password, Buffer.from(saltHex, 'hex'), PBKDF2_ITER, 32, 'sha256').toString('hex');
}

function verifyPassword(password, saltHex, expectedHash) {
  const a = Buffer.from(hashPassword(password, saltHex), 'hex');
  const b = Buffer.from(expectedHash, 'hex');
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function makeUuid(email, createdAt) {
  // Deterministic user id derived from email + creation time (36-char uuid).
  const digest = crypto.createHash('sha256').update(`${email}|${createdAt}`).digest('hex');
  const h = digest.slice(0, 32);
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20, 32)}`;
}

// 免密直达链接 token（等价于一本书签，随身可复制）。存明文便于随时回显；随机关闭会被清空。
function genLinkToken() {
  return crypto.randomBytes(24).toString('base64url');
}

// ------------------------------------------------------------------- auth
function issueToken(userId) {
  const token = crypto.randomBytes(24).toString('hex');
  TOKENS.set(token, { userId, expires: Date.now() / 1000 + TOKEN_TTL });
  return token;
}

function userForToken(token) {
  const rec = TOKENS.get(token);
  if (!rec) return null;
  if (rec.expires < Date.now() / 1000) {
    TOKENS.delete(token);
    return null;
  }
  return rec.userId;
}

// ------------------------------------------------------------------ helpers
function nowSec() { return Math.floor(Date.now() / 1000); }

function fmtNow() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function readJson(req) {
  return new Promise((resolve) => {
    const size = parseInt(req.headers['content-length'] || '0', 10) || 0;
    if (size <= 0) return resolve({});
    const chunks = [];
    let got = 0;
    req.on('data', (c) => { chunks.push(c); got += c.length; });
    req.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
      catch (_) { resolve({}); }
    });
    req.on('error', () => resolve({}));
  });
}

function sendJson(res, obj, status = 200) {
  const body = Buffer.from(JSON.stringify(obj), 'utf8');
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': body.length,
  });
  res.end(body);
}

function sendError(res, msg, status = 400) {
  sendJson(res, { ok: false, error: msg }, status);
}

function logRequest(req, status) {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const line = `[${p(d.getDate())}/${months[d.getMonth()]}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}] "${req.method} ${req.url} HTTP/1.1" ${status} -`;
  try { process.stdout.write(line + '\n'); } catch (_) { /* never crash on logging */ }
}

// ------------------------------------------------------------------- auth
function auth(req, res) {
  const ah = req.headers['authorization'] || '';
  const token = ah.startsWith('Bearer ') ? ah.slice(7) : '';
  const uid = token ? userForToken(token) : null;
  if (uid == null) {
    sendError(res, '未登录或登录已过期', 401);
    return null;
  }
  const row = db.prepare('SELECT id, username, nickname, uuid, role FROM users WHERE id = ?').get(uid);
  if (!row) {
    sendError(res, '用户不存在', 401);
    return null;
  }
  return row;
}

function requireAdmin(req, res) {
  const user = auth(req, res);
  if (!user) return null;
  if (user.role !== 'admin') {
    sendError(res, '需要管理员权限', 403);
    return null;
  }
  return user;
}

// ------------------------------------------------------------ membership
// 会员 / 钻石系统：
//   密钥    -> 7 天 / 14 天会员。有效期内：每日保底 +1 金碎片，且免疫黑色碎片侵袭
//   奖励    -> 每日练习每凑满一轮随机 21-27 道触发一次奖励（随机 1-3 金碎片）
//   兑换    -> 金色碎片 ≥21 时变为可兑换状态，玩家可手动消耗 21 碎片兑换
//              黄钻等级 +1（首次=一级黄钻），剩余碎片保留继续累积
//   黑色    -> 次日练习 ≤3 出现 3-5 个黑色碎片，1:1 吃掉金碎片；
//              金碎片被吃光后黄钻进入消耗：一级保留 1 天、二级 2 天…（grace_days），
//              超过保留天数则黄钻降 1 级；一级以下新手只被吃掉 1 个碎片
//   结算    -> 服务端每日自动结算（延迟补算所有未结算的日期）
const KEY_TYPES = ['7d', '14d'];
const KEY_DAYS = { '7d': 7, '14d': 14 };
const DAY_SEC = 86400;
const PRACTICE_LOG_KEY = 'brand9::practiceLog::v1';   // 与前端 LOG_KEY 一致

function dayKey(ts) {
  // UTC 日期字符串，与前端 new Date().toISOString().substring(0,10) 对齐
  return new Date(ts == null ? Date.now() : ts).toISOString().substring(0, 10);
}
function dayStartSec(day) { return Date.parse(day + 'T00:00:00Z') / 1000; }

function ensureMember(userId) {
  const row = db.prepare('SELECT * FROM membership WHERE user_id = ?').get(userId);
  if (row) return row;
  db.prepare('INSERT INTO membership (user_id, gold, yd_level, grace_days, updated_at) VALUES (?,0,0,0,?)')
    .run(userId, nowSec());
  return db.prepare('SELECT * FROM membership WHERE user_id = ?').get(userId);
}

function updateMember(userId, mem) {
  db.prepare(`UPDATE membership SET key_type=?, key_start=?, key_expires=?, gold=?,
              yd_level=?, grace_days=?, last_day_reward=?, last_status_day=?, updated_at=? WHERE user_id=?`)
    .run(mem.key_type || null, mem.key_start || 0, mem.key_expires || 0,
         mem.gold || 0, mem.yd_level || 0, mem.grace_days || 0,
         mem.last_day_reward || 0, mem.last_status_day || null, nowSec(), userId);
}

function practiceCountForDay(userId, day) {
  const row = db.prepare('SELECT value FROM user_state WHERE user_id=? AND key=?').get(userId, PRACTICE_LOG_KEY);
  if (!row || !row.value) return 0;
  try {
    const arr = JSON.parse(row.value);
    if (!Array.isArray(arr)) return 0;
    return arr.filter((e) => e && e.date === day).length;
  } catch (_) { return 0; }
}

// 当日奖励参数用 (用户, 日期, 轮次) 作确定性种子 —— 同一用户同一天重复结算结果一致，
// 这样「当天练满后再次打开会员中心」能补算新增奖励，而不会重复发放。
function hashStr(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function rngFrom(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
function roundThreshold(userId, day, ri) {
  return 21 + Math.floor(rngFrom(hashStr(userId + '|' + day + '|' + ri + '|th'))() * 7);   // 21-27
}
function roundReward(userId, day, ri) {
  return 1 + Math.floor(rngFrom(hashStr(userId + '|' + day + '|' + ri + '|rw'))() * 3);    // 1-3
}
function rewardForCount(userId, day, cnt) {
  let rem = cnt, ri = 0, g = 0;
  while (rem >= 21) {
    const threshold = roundThreshold(userId, day, ri);   // 21-27 随机
    if (rem < threshold) break;
    rem -= threshold;
    g += roundReward(userId, day, ri);                   // 1-3 随机
    ri += 1;
  }
  return g;
}

// 结算某用户从「上次结算日」到今天的每一天（含）。

function settleMember(userId) {
  const mem = ensureMember(userId);
  const today = dayKey(Date.now());
  let gold = mem.gold || 0;
  let level = mem.yd_level || 0;
  let grace = mem.grace_days || 0;
  let dayReward = mem.last_day_reward || 0;   // 已按「今天」累计发放的练满奖励快照
  const keyStart = mem.key_start || 0;
  const keyExpires = mem.key_expires || 0;
  let lastDay = mem.last_status_day || null;
  const alreadySettledToday = lastDay === today;

  const processDay = (d, applyOnce) => {
    const ds = dayStartSec(d);
    const keyActive = keyStart && keyExpires && ds >= keyStart && ds < keyExpires;
    const cnt = practiceCountForDay(userId, d);

    if (applyOnce && keyActive) gold += 1;        // 密钥期内每日保底 +1（仅当天首结算）

    if (cnt >= 21) {
      // 每凑满一轮随机 21-27 道触发一次，奖励 1-3 金碎片（确定性种子）
      // 当天重复结算时只补发差额（新增练满带来的金），不重复累计。
      const full = rewardForCount(userId, d, cnt);
      const granted = Math.max(0, full - dayReward);
      gold += granted;
      dayReward = full;
      if (applyOnce && gold > 0) grace = 0;      // 有碎片兜底，黄钻不再消耗
    } else if (cnt <= 3 && !keyActive && applyOnce) {
      const black = 3 + crypto.randomInt(0, 3);   // 3-5 个黑色碎片（仅当天首结算）
      if (level >= 1) {
        const consumed = Math.min(black, gold);
        gold -= consumed;
        if (gold <= 0) {
          gold = 0;
          // 碎片不够消耗：黄钻进入消耗期，一级保留 1 天、二级 2 天…
          if (grace >= level) { level = Math.max(0, level - 1); grace = 0; }
          else grace += 1;
        } else {
          grace = 0;
        }
      } else {
        if (gold > 0) gold -= 1;                 // 新手保护：只被吃掉 1 个
      }
    }
    // 4-20 题：无奖励、无惩罚
  };

  if (!lastDay) {
    processDay(today, true);                 // 首次结算：从今天开始，不追溯历史
  } else if (alreadySettledToday) {
    processDay(today, false);                // 当天补算：只补练满奖励差额
  } else {
    let cur = dayStartSec(lastDay) + DAY_SEC;
    const end = dayStartSec(today);
    for (; cur <= end; cur += DAY_SEC) {
      const d = dayKey(cur * 1000);
      dayReward = 0;                          // 补算期间每一天都是全新的
      processDay(d, true);
    }
  }
  mem.gold = gold; mem.yd_level = level; mem.grace_days = grace;
  mem.last_day_reward = dayReward;
  mem.last_status_day = today;
  updateMember(userId, mem);
  return ensureMember(userId);
}

// 全局结算所有用户（定时 + 排行榜读取时调用）。
function settleAllUsers() {
  for (const r of db.prepare('SELECT id FROM users').all()) settleMember(r.id);
}

function memberCat(mem) {
  if (mem.yd_level >= 1) return 'yellow';
  return 'white';   // 一级以下统一为白钻（新手）；密钥只是额外的保护/保底权益
}

function keyActiveUntil(mem) {
  const now = nowSec();
  if (mem.key_type && mem.key_expires && mem.key_expires > now) return mem.key_expires;
  return 0;
}

// 密钥码：BR9-XXXX-XXXX-XXXX-XXXX（无易混淆字符），入库时去掉分隔符
const KEY_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const KEY_PREFIX = 'BR9';
function genKeyCode() {
  let s = '';
  for (let i = 0; i < 16; i++) s += KEY_ALPHABET[crypto.randomInt(KEY_ALPHABET.length)];
  return KEY_PREFIX + s;
}
function formatKeyCode(raw) {
  const b = raw.slice(KEY_PREFIX.length);
  return KEY_PREFIX + '-' + b.slice(0, 4) + '-' + b.slice(4, 8) + '-' + b.slice(8, 12) + '-' + b.slice(12, 16);
}
function normalizeKeyCode(input) {
  return String(input || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

// -------------------------------------------------------------------- API
async function apiSendCode(req, res) {
  const data = await readJson(req);
  const email = String(data.email || '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) return sendError(res, '邮箱格式不正确');
  const now = nowSec();
  const existing = db.prepare('SELECT 1 FROM users WHERE email = ?').get(email);
  if (existing) return sendError(res, '该邮箱已被注册', 409);
  const row = db.prepare('SELECT sent_at FROM email_codes WHERE email = ?').get(email);
  if (row) {
    const wait = RESEND_INTERVAL - (now - row.sent_at);
    if (wait > 0) {
      return sendJson(res, { ok: false, error: `发送太频繁，请 ${wait} 秒后再试`, wait }, 429);
    }
  }
  const code = String(crypto.randomInt(0, 1000000)).padStart(6, '0');
  db.prepare('DELETE FROM email_codes WHERE email = ?').run(email);
  db.prepare('INSERT INTO email_codes (email, code, sent_at, expires_at) VALUES (?,?,?,?)')
    .run(email, code, now, now + CODE_TTL);
  const err = await sendVerificationEmail(email, code);
  if (err) {
    db.prepare('DELETE FROM email_codes WHERE email = ?').run(email);
    return sendError(res, err, 500);
  }
  return sendJson(res, { ok: true, wait: RESEND_INTERVAL, ttl: CODE_TTL });
}

async function apiRegister(req, res) {
  const data = await readJson(req);
  const email = String(data.email || '').trim().toLowerCase();
  const password = String(data.password || '');
  const code = String(data.code || '').trim();
  const nickname = String(data.nickname || '').trim();
  if (!(password.length >= 6 && password.length <= 128)) return sendError(res, '密码需为 6-128 个字符');
  if (!EMAIL_RE.test(email)) return sendError(res, '邮箱格式不正确');
  const now = nowSec();
  if (db.prepare('SELECT 1 FROM users WHERE email = ?').get(email)) {
    return sendError(res, '该邮箱已被注册', 409);
  }
  const row = db.prepare('SELECT code, expires_at FROM email_codes WHERE email = ?').get(email);
  if (!row || row.expires_at < now) return sendError(res, '验证码不存在或已过期，请先获取验证码');
  if (row.code !== code) return sendError(res, '验证码错误');
  const salt = crypto.randomBytes(16).toString('hex');
  const pwHash = hashPassword(password, salt);
  const createdAt = fmtNow();
  const userUuid = makeUuid(email, createdAt);
  const display = nickname || email.split('@')[0];
  let userId;
  try {
    const r = db.prepare(
      'INSERT INTO users (username, pass_salt, pass_hash, created_at, email, nickname, uuid) VALUES (?,?,?,?,?,?,?)'
    ).run(userUuid, salt, pwHash, createdAt, email, display, userUuid);
    userId = Number(r.lastInsertRowid);
    db.prepare('DELETE FROM email_codes WHERE email = ?').run(email);
  } catch (e) {
    if (String(e.message).includes('UNIQUE')) return sendError(res, '该邮箱已被注册', 409);
    throw e;
  }
  const token = issueToken(userId);
  return sendJson(res, { ok: true, token, username: display, uuid: userUuid });
}

async function apiLogin(req, res) {
  const data = await readJson(req);
  const ident = String(data.username || '').trim();
  const email = String(data.email || '').trim().toLowerCase() || ident;
  const password = String(data.password || '');
  const row = db.prepare(
    'SELECT id, username, nickname, uuid, role, pass_salt, pass_hash FROM users WHERE email = ? OR username = ?'
  ).get(email, ident);
  if (!row || !verifyPassword(password, row.pass_salt, row.pass_hash)) {
    return sendError(res, '邮箱或密码错误', 401);
  }
  const token = issueToken(row.id);
  const display = row.nickname || row.username;
  return sendJson(res, { ok: true, token, username: display, uuid: row.uuid || '', role: row.role || 'user' });
}

function apiLogout(req, res) {
  const ah = req.headers['authorization'] || '';
  if (ah.startsWith('Bearer ')) TOKENS.delete(ah.slice(7));
  return sendJson(res, { ok: true });
}

// 免密直达链接：用链接里的 token 换取正常会话。
// 仅当账号「开放可见性」(link_open) 或为管理员时才有效；关闭时会清空 token，旧链接即失效。
async function apiLoginLink(req, res) {
  const data = await readJson(req);
  const token = String(data.token || '').trim();
  if (!token) return sendError(res, '缺少直达链接 token');
  const row = db.prepare('SELECT id, username, nickname, uuid, role, link_open FROM users WHERE login_token = ?').get(token);
  if (!row) return sendError(res, '直达链接无效或已失效', 401);
  if (row.role !== 'admin' && row.link_open !== 1) return sendError(res, '该直达链接已被关闭', 401);
  const userToken = issueToken(row.id);
  const display = row.nickname || row.username;
  return sendJson(res, { ok: true, token: userToken, username: display, uuid: row.uuid || '', role: row.role || 'user' });
}

function rowLinkState(row) {
  const open = row.role === 'admin' || (row.link_open || 0) === 1;
  return { open, token: open && row.login_token ? row.login_token : null };
}

function apiMeLinkGet(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const row = db.prepare('SELECT id, role, link_open, login_token FROM users WHERE id = ?').get(user.id);
  if (!row) return sendError(res, '用户不存在', 404);
  return sendJson(res, { ok: true, ...rowLinkState(row) });
}

async function apiMeLinkGen(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const row = db.prepare('SELECT id, role, link_open FROM users WHERE id = ?').get(user.id);
  const st = rowLinkState(row);
  if (!st.open) return sendError(res, '管理员还未对你开放此功能', 403);
  const token = genLinkToken();
  db.prepare('UPDATE users SET login_token = ? WHERE id = ?').run(token, user.id);
  return sendJson(res, { ok: true, open: true, token });
}

async function apiAdminLinkGet(req, res, uid) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  if (!isManaged(uid)) return sendError(res, '无权限操作该账号', 403);
  const row = db.prepare('SELECT id, role, link_open, login_token FROM users WHERE id = ?').get(uid);
  if (!row) return sendError(res, '用户不存在', 404);
  return sendJson(res, { ok: true, ...rowLinkState(row) });
}

async function apiAdminLinkSet(req, res, uid) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  if (!isManaged(uid)) return sendError(res, '无权限操作该账号', 403);
  const row = db.prepare('SELECT id, role FROM users WHERE id = ?').get(uid);
  if (!row) return sendError(res, '用户不存在', 404);
  if (row.role === 'admin') return sendError(res, '管理员账号默认开放，无需开关');
  const data = await readJson(req);
  const open = data.open === true;
  if (open) {
    const token = genLinkToken();
    db.prepare('UPDATE users SET link_open = 1, login_token = ? WHERE id = ?').run(token, uid);
    return sendJson(res, { ok: true, open: true, token });
  }
  db.prepare('UPDATE users SET link_open = 0, login_token = NULL WHERE id = ?').run(uid);
  return sendJson(res, { ok: true, open: false, token: null });
}

function apiMe(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const display = user.nickname || user.username;
  return sendJson(res, { ok: true, username: display, uuid: user.uuid || '', role: user.role || 'user' });
}

async function apiSetNickname(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const data = await readJson(req);
  const nickname = String(data.nickname || '').trim();
  if (!(nickname.length >= 1 && nickname.length <= 32)) return sendError(res, '昵称需为 1-32 个字符');
  db.prepare('UPDATE users SET nickname = ? WHERE id = ?').run(nickname, user.id);
  return sendJson(res, { ok: true, username: nickname });
}

function apiStateGet(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const rows = db.prepare('SELECT key, value, updated_at FROM user_state WHERE user_id = ?').all(user.id);
  const state = {};
  for (const r of rows) state[r.key] = { value: r.value, updated_at: r.updated_at };
  return sendJson(res, { ok: true, state });
}

async function apiStateSync(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const data = await readJson(req);
  const entries = data.entries;
  if (!Array.isArray(entries)) return sendError(res, 'entries 必须为数组');
  const upsert = db.prepare(
    `INSERT INTO user_state (user_id, key, value, updated_at) VALUES (?,?,?,?)
     ON CONFLICT(user_id, key) DO UPDATE SET
       value      = excluded.value,
       updated_at = excluded.updated_at
     WHERE excluded.updated_at >= user_state.updated_at`
  );
  let saved = 0;
  for (const e of entries) {
    const key = String(e.key || '');
    const value = e.value;
    const ts = parseInt(e.updated_at, 10) || 0;
    if (!key || value == null) continue;
    const v = typeof value === 'string' ? value : JSON.stringify(value);
    const r = upsert.run(user.id, key, v, ts);
    if (r.changes > 0) saved++;
  }
  return sendJson(res, { ok: true, saved });
}

function apiStateClear(req, res) {
  const user = auth(req, res);
  if (!user) return;
  db.prepare('DELETE FROM user_state WHERE user_id = ?').run(user.id);
  return sendJson(res, { ok: true });
}

// ------------------------------------------------------------- admin
function apiAdminMe(req, res) {
  const user = auth(req, res);
  if (!user) return;
  return sendJson(res, { ok: true, username: user.username, role: user.role });
}

function apiAdminAccounts(req, res) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  settleAllUsers();
  const rows = db.prepare(
    `SELECT u.id, u.username, u.email, u.note, u.created_at, u.role, u.parent_id,
            u.link_open, u.login_token,
            COALESCE(m.gold,0) AS gold, COALESCE(m.yd_level,0) AS yd_level, m.key_type, m.key_expires
     FROM users u LEFT JOIN membership m ON m.user_id = u.id
     ORDER BY u.created_at`
  ).all();
  const out = rows.map((r) => ({
    id: r.id, username: r.username, email: r.email, note: r.note, created_at: r.created_at,
    role: r.role, parent_id: r.parent_id,
    link_open: r.role === 'admin' || (r.link_open === 1),   // 管理员默认开放
    has_link: !!(r.login_token),
    member: { gold: r.gold, yd_level: r.yd_level,
              key_type: r.key_type, key_expires: r.key_expires || 0 },
  }));
  return sendJson(res, { ok: true, accounts: out });
}

async function apiAdminCreate(req, res) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  const data = await readJson(req);
  const username = String(data.username || '').trim();
  const password = String(data.password || '');
  const email = String(data.email || '').trim().toLowerCase();
  const note = String(data.note || '');
  if (!(username.length >= 3 && username.length <= 32)) return sendError(res, '用户名需为 3-32 个字符');
  if (!(password.length >= 6 && password.length <= 128)) return sendError(res, '密码需为 6-128 个字符');
  if (email && !EMAIL_RE.test(email)) return sendError(res, '邮箱格式不正确');
  const salt = crypto.randomBytes(16).toString('hex');
  const pwHash = hashPassword(password, salt);
  let uid;
  try {
    const r = db.prepare(
      'INSERT INTO users (username, pass_salt, pass_hash, created_at, email, role, parent_id, note) VALUES (?,?,?,?,?,?,?,?)'
    ).run(username, salt, pwHash, fmtNow(), email || null, 'user', admin.id, note);
    uid = Number(r.lastInsertRowid);
  } catch (e) {
    if (String(e.message).includes('UNIQUE')) return sendError(res, '用户名已被注册', 409);
    throw e;
  }
  return sendJson(res, { ok: true, id: uid, username });
}

function isManaged(uid) {
  return !!db.prepare('SELECT id FROM users WHERE id = ?').get(uid);
}

async function apiAdminReset(req, res, uid) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  if (uid === admin.id) return sendError(res, '不能重置自己的密码');
  const data = await readJson(req);
  const password = String(data.password || '');
  if (!(password.length >= 6 && password.length <= 128)) return sendError(res, '密码需为 6-128 个字符');
  if (!isManaged(uid)) return sendError(res, '无权限操作该账号', 403);
  const salt = crypto.randomBytes(16).toString('hex');
  const pwHash = hashPassword(password, salt);
  db.prepare('UPDATE users SET pass_salt = ?, pass_hash = ? WHERE id = ?').run(salt, pwHash, uid);
  return sendJson(res, { ok: true });
}

async function apiAdminUpdate(req, res, uid) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  const data = await readJson(req);
  if (!isManaged(uid)) return sendError(res, '无权限操作该账号', 403);
  if (data.note != null) {
    db.prepare('UPDATE users SET note = ? WHERE id = ?').run(String(data.note), uid);
  }
  if (data.email != null) {
    let email = String(data.email).trim().toLowerCase();
    if (email && !EMAIL_RE.test(email)) return sendError(res, '邮箱格式不正确');
    db.prepare('UPDATE users SET email = ? WHERE id = ?').run(email || null, uid);
  }
  return sendJson(res, { ok: true });
}

function apiAdminSmtpGet(req, res) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  const u = db.prepare("SELECT v FROM kv WHERE k='smtp_user'").get();
  const p = db.prepare("SELECT v FROM kv WHERE k='smtp_pass'").get();
  return sendJson(res, { ok: true, qq_email: u && u.v ? u.v : '', qq_key: p && p.v ? p.v : '' });
}

async function apiAdminSmtpSet(req, res) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  const data = await readJson(req);
  const qq_email = String(data.qq_email || '').trim();
  const qq_key = String(data.qq_key || '');
  if (qq_email && !EMAIL_RE.test(qq_email)) return sendError(res, 'QQ 邮箱格式不正确');
  db.prepare("INSERT INTO kv (k, v) VALUES ('smtp_user', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v").run(qq_email);
  db.prepare("INSERT INTO kv (k, v) VALUES ('smtp_pass', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v").run(qq_key);
  return sendJson(res, { ok: true });
}

async function apiAdminKeysGen(req, res) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  const data = await readJson(req);
  const type = String(data.type || '');
  const count = Math.min(parseInt(data.count, 10) || 1, 50);
  if (!KEY_TYPES.includes(type)) return sendError(res, '密钥类型需为 7d 或 14d');
  const insert = db.prepare('INSERT INTO vip_keys (code, type, created_by, created_at) VALUES (?,?,?,?)');
  const codes = [];
  while (codes.length < count) {
    const code = genKeyCode();
    try { insert.run(code, type, admin.id, nowSec()); codes.push(formatKeyCode(code)); }
    catch (e) { if (!String(e.message).includes('UNIQUE')) throw e; }
  }
  return sendJson(res, { ok: true, type, codes });
}

function apiAdminKeysList(req, res) {
  const admin = requireAdmin(req, res);
  if (!admin) return;
  const rows = db.prepare('SELECT code, type, used_by, used_at, created_by, created_at FROM vip_keys ORDER BY created_at DESC LIMIT 200').all();
  const out = rows.map((r) => ({
    code: formatKeyCode(r.code), type: r.type,
    used: r.used_by ? true : false, used_by: r.used_by || 0, used_at: r.used_at || 0, created_at: r.created_at || 0,
  }));
  return sendJson(res, { ok: true, keys: out });
}

function apiMembershipMe(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const mem = settleMember(user.id);
  const expire = keyActiveUntil(mem);
  return sendJson(res, {
    ok: true,
    cat: memberCat(mem),
    key_type: expire ? mem.key_type : null,
    key_start: expire ? (mem.key_start || 0) : 0,
    key_expires: expire,
    gold: mem.gold,
    yd_level: mem.yd_level,
    grace_days: mem.grace_days || 0,
    redeemable: mem.gold >= 21,
  });
}

async function apiConvertDiamond(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const mem = settleMember(user.id);
  if (mem.gold < 21) return sendError(res, `金色碎片不足，还差 ${21 - mem.gold} 个才能兑换`);
  mem.gold -= 21;
  mem.yd_level += 1;              // 首次兑换=一级黄钻，此后每兑换一次 +1 级
  mem.grace_days = 0;
  updateMember(user.id, mem);
  const fresh = ensureMember(user.id);
  return sendJson(res, {
    ok: true,
    gold: fresh.gold,
    yd_level: fresh.yd_level,
    grace_days: fresh.grace_days || 0,
    redeemable: fresh.gold >= 21,
  });
}

async function apiActivateKey(req, res) {
  const user = auth(req, res);
  if (!user) return;
  const data = await readJson(req);
  const code = normalizeKeyCode(data.code);
  if (code.length < 8) return sendError(res, '密钥格式不正确，请检查后重试');
  const row = db.prepare('SELECT code, type, used_by FROM vip_keys WHERE code = ?').get(code);
  if (!row) return sendError(res, '密钥不存在');
  if (row.used_by) return sendError(res, '密钥已被使用');
  const days = KEY_DAYS[row.type];
  const mem = settleMember(user.id);
  const now = nowSec();
  const base = (mem.key_expires && mem.key_expires > now) ? mem.key_expires : now;
  db.prepare('UPDATE vip_keys SET used_by = ?, used_at = ? WHERE code = ?').run(user.id, now, row.code);
  mem.key_type = row.type;
  mem.key_start = now;
  mem.key_expires = base + days * DAY_SEC;
  mem.gold += 1;                                   // 激活即送 1 个金碎片
  updateMember(user.id, mem);
  return sendJson(res, { ok: true, expire: mem.key_expires, type: row.type });
}

function apiScoreboard(req, res) {
  const user = auth(req, res);
  if (!user) return;
  settleAllUsers();
  const rows = db.prepare(
    `SELECT u.id, u.username, COALESCE(m.gold,0) AS gold, COALESCE(m.yd_level,0) AS yd_level,
            m.key_type, m.key_expires
     FROM users u LEFT JOIN membership m ON m.user_id = u.id
     ORDER BY gold DESC, u.created_at ASC`
  ).all();
  const out = rows.map((r) => ({
    id: r.id, username: r.username, gold: r.gold,
    cat: r.yd_level >= 1 ? 'yellow' : 'white',   // 一级以下统一为白钻
    yd_level: r.yd_level,
  }));
  return sendJson(res, { ok: true, board: out });
}

// -------------------------------------------------------------- static
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav',
  '.mp4': 'video/mp4',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8',
  '.pdf': 'application/pdf',
  '.wasm': 'application/wasm',
};

// Block dotfiles (.env/.git/...) and sensitive extensions from being served.
const SENSITIVE_RE = /(?:^|\/)\.|\.(?:py|db|sh|log|pem|key|crt|env|conf)(?:$|\/)/i;

function serveStatic(req, res, pathname) {
  let decoded;
  try { decoded = decodeURIComponent(pathname); } catch (_) { return send404(res); }
  const rel = decoded === '/' ? 'index.html' : decoded.replace(/^\/+/, '');
  if (SENSITIVE_RE.test(rel)) return send404(res);
  const abs = path.resolve(DIR, rel);
  const absDir = path.resolve(DIR);
  if (abs !== absDir && !abs.startsWith(absDir + path.sep)) return send404(res);
  fs.stat(abs, (err, st) => {
    if (err || !st.isFile()) return send404(res);
    const ext = path.extname(abs).toLowerCase();
    const mime = MIME[ext] || 'application/octet-stream';
    const cc = ext === '.mp3' ? 'public, max-age=31536000, immutable' : 'public, max-age=600';
    const lastMod = st.mtime.toUTCString();
    if (req.headers['if-modified-since'] === lastMod) {
      res.writeHead(304, { 'Cache-Control': cc, 'Last-Modified': lastMod });
      return res.end();
    }
    res.writeHead(200, {
      'Content-Type': mime,
      'Cache-Control': cc,
      'Last-Modified': lastMod,
      'Content-Length': st.size,
    });
    if (req.method === 'HEAD') return res.end();
    const stream = fs.createReadStream(abs);
    stream.on('error', () => { try { res.destroy(); } catch (_) { /* ignore */ } });
    stream.pipe(res);
  });
}

function send404(res) {
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end('404 Not Found');
}

// --------------------------------------------------------------- router
async function apiRouter(req, res, method, p) {
  const A = (fn) => fn(req, res);
  if (p === '/api/register' && method === 'POST') return await A(apiRegister);
  if (p === '/api/send_code' && method === 'POST') return await A(apiSendCode);
  if (p === '/api/login' && method === 'POST') return await A(apiLogin);
  if (p === '/api/login/link' && method === 'POST') return await A(apiLoginLink);
  if (p === '/api/logout' && method === 'POST') return A(apiLogout);
  if (p === '/api/me' && method === 'GET') return A(apiMe);
  if (p === '/api/me' && method === 'POST') return await A(apiSetNickname);
  if (p === '/api/me/link' && method === 'GET') return A(apiMeLinkGet);
  if (p === '/api/me/link/gen' && method === 'POST') return await A(apiMeLinkGen);
  if (p === '/api/state' && method === 'GET') return A(apiStateGet);
  if (p === '/api/state/sync' && method === 'POST') return await A(apiStateSync);
  if (p === '/api/state/clear' && method === 'POST') return A(apiStateClear);
  if (p === '/api/admin/me' && method === 'GET') return A(apiAdminMe);
  if (p === '/api/admin/accounts' && method === 'GET') return A(apiAdminAccounts);
  if (p === '/api/admin/accounts' && method === 'POST') return await A(apiAdminCreate);
  if (p === '/api/admin/smtp' && method === 'GET') return A(apiAdminSmtpGet);
  if (p === '/api/admin/smtp' && method === 'PUT') return await A(apiAdminSmtpSet);
  if (p === '/api/admin/keys' && method === 'GET') return A(apiAdminKeysList);
  if (p === '/api/admin/keys' && method === 'POST') return await A(apiAdminKeysGen);
  if (p === '/api/membership/me' && method === 'GET') return A(apiMembershipMe);
  if (p === '/api/membership/convert' && method === 'POST') return A(apiConvertDiamond);
  if (p === '/api/membership/activate' && method === 'POST') return await A(apiActivateKey);
  if (p === '/api/scoreboard' && method === 'GET') return A(apiScoreboard);
  let m = p.match(/^\/api\/admin\/accounts\/(\d+)$/);
  if (m && method === 'PUT') return await A((req, res) => apiAdminUpdate(req, res, Number(m[1])));
  m = p.match(/^\/api\/admin\/accounts\/(\d+)\/link$/);
  if (m && method === 'GET') return await A((req, res) => apiAdminLinkGet(req, res, Number(m[1])));
  if (m && method === 'PUT') return await A((req, res) => apiAdminLinkSet(req, res, Number(m[1])));
  m = p.match(/^\/api\/admin\/accounts\/(\d+)\/reset$/);
  if (m && method === 'POST') return await A((req, res) => apiAdminReset(req, res, Number(m[1])));
  return sendError(res, `未知接口: ${method} ${p}`, 404);
}

const server = http.createServer(async (req, res) => {
  let url;
  try { url = new URL(req.url, 'http://localhost'); }
  catch (_) { return sendError(res, '非法请求', 400); }
  const p = url.pathname;
  const method = req.method || 'GET';
  try {
    if (p.startsWith('/api/')) {
      const started = Date.now();
      await apiRouter(req, res, method, p);
      logRequest(req, res.statusCode || 200);
      return;
    }
    serveStatic(req, res, p);
    res.on('finish', () => logRequest(req, res.statusCode));
  } catch (e) {
    console.error('[error]', e);
    if (!res.headersSent) sendError(res, '服务器错误', 500);
  }
});

// ------------------------------------------------------------------- main
initDb();

const tlsEnabled = process.env.BRAND9_TLS === '1';
const tlsCert = process.env.BRAND9_CERT || path.join(DIR, '10.110.218.198+1.pem');
const tlsKey = process.env.BRAND9_KEY || path.join(DIR, '10.110.218.198+1-key.pem');

if (tlsEnabled) {
  if (!(fs.existsSync(tlsCert) && fs.existsSync(tlsKey))) {
    console.error(`ERROR: BRAND9_TLS=1 but cert/key not found:\n  ${tlsCert}\n  ${tlsKey}`);
    process.exit(1);
  }
  const secureServer = https.createServer({ cert: fs.readFileSync(tlsCert), key: fs.readFileSync(tlsKey) }, server.requestListener);
  secureServer.listen(PORT, '0.0.0.0', () => console.log(`Serving ${DIR} on https://0.0.0.0:${PORT}`));
} else {
  server.listen(PORT, '0.0.0.0', () => console.log(`Serving ${DIR} on http://0.0.0.0:${PORT}`));
}

// 会员结算：每 30 分钟全量结算一次（也让离线用户按时吃到每日奖励/惩罚）
setInterval(() => { try { settleAllUsers(); } catch (e) { console.error('[settle]', e); } }, 30 * 60 * 1000);
