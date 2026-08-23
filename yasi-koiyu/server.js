// brand9 server (Node.js): static files + user accounts + SQLite-backed progress sync.
//
// Zero third-party dependencies (node:http + node:sqlite + node:crypto + node:tls).
// Drop-in equivalent of the former server.py. Endpoints:
//   POST /api/send_code          {email} -> 6-digit verification email
//   POST /api/register           {username, password, email, code}
//   POST /api/login              {username, password} -> {token}
//   POST /api/logout             (Bearer) -> invalidates token
//   GET  /api/me                 (Bearer) -> {username}
//   GET  /api/state              (Bearer) -> {key: {value, updated_at}}
//   POST /api/state/sync         (Bearer) {entries:[{key, value, updated_at}]}
//   POST /api/state/clear        (Bearer) -> wipe user state (keep account)
//   Admin: /api/admin/me|accounts|accounts/:id|accounts/:id/reset|smtp
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

// ------------------------------------------------------- smtp (shared w/ dw-shop)
function readDwshopEnv() {
  // Read SMTP settings from dw-shop's .env so both apps share one credential.
  const envPath = path.join(DIR, '..', 'fun', 'dw-shop', '.env');
  const out = {};
  try {
    const txt = fs.readFileSync(envPath, 'utf8');
    for (const raw of txt.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const i = line.indexOf('=');
      const k = line.slice(0, i).trim();
      let v = line.slice(i + 1).trim();
      v = v.replace(/^["']/, '').replace(/["']$/, '');
      out[k] = v;
    }
  } catch (_) { /* no dw-shop env */ }
  return out;
}

const DWSHOP_ENV = readDwshopEnv();
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

async function sendVerificationEmail(email, code) {
  const creds = getSmtpCreds();
  if (!creds.user || !creds.pass) return 'SMTP 未配置（请在管理员后台填写 QQ 邮箱与授权码）';
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
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
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
  `);
  const cols = db.prepare('PRAGMA table_info(users)').all().map((r) => r.name);
  if (!cols.includes('email')) db.exec('ALTER TABLE users ADD COLUMN email TEXT');
  if (!cols.includes('role')) db.exec("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'");
  if (!cols.includes('parent_id')) db.exec('ALTER TABLE users ADD COLUMN parent_id INTEGER');
  if (!cols.includes('note')) db.exec('ALTER TABLE users ADD COLUMN note TEXT');
  db.exec('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)');
  db.exec('CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);');
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
  const row = db.prepare('SELECT id, username, role FROM users WHERE id = ?').get(uid);
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
  const username = String(data.username || '').trim();
  const password = String(data.password || '');
  const email = String(data.email || '').trim().toLowerCase();
  const code = String(data.code || '').trim();
  if (!(username.length >= 3 && username.length <= 32)) return sendError(res, '用户名需为 3-32 个字符');
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
  let userId;
  try {
    const r = db.prepare(
      'INSERT INTO users (username, pass_salt, pass_hash, created_at, email) VALUES (?,?,?,?,?)'
    ).run(username, salt, pwHash, fmtNow(), email);
    userId = Number(r.lastInsertRowid);
    db.prepare('DELETE FROM email_codes WHERE email = ?').run(email);
  } catch (e) {
    if (String(e.message).includes('UNIQUE')) return sendError(res, '用户名已被注册', 409);
    throw e;
  }
  const token = issueToken(userId);
  return sendJson(res, { ok: true, token, username });
}

async function apiLogin(req, res) {
  const data = await readJson(req);
  const username = String(data.username || '').trim();
  const password = String(data.password || '');
  const row = db.prepare('SELECT id, username, pass_salt, pass_hash FROM users WHERE username = ?').get(username);
  if (!row || !verifyPassword(password, row.pass_salt, row.pass_hash)) {
    return sendError(res, '用户名或密码错误', 401);
  }
  const token = issueToken(row.id);
  return sendJson(res, { ok: true, token, username: row.username });
}

function apiLogout(req, res) {
  const ah = req.headers['authorization'] || '';
  if (ah.startsWith('Bearer ')) TOKENS.delete(ah.slice(7));
  return sendJson(res, { ok: true });
}

function apiMe(req, res) {
  const user = auth(req, res);
  if (!user) return;
  return sendJson(res, { ok: true, username: user.username });
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
  const rows = db.prepare(
    'SELECT id, username, email, note, created_at, role, parent_id FROM users ORDER BY created_at'
  ).all();
  return sendJson(res, { ok: true, accounts: rows });
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

function serveStatic(req, res, pathname) {
  let decoded;
  try { decoded = decodeURIComponent(pathname); } catch (_) { return send404(res); }
  const rel = decoded === '/' ? 'index.html' : decoded.replace(/^\/+/, '');
  const abs = path.resolve(DIR, rel);
  const absDir = path.resolve(DIR);
  if (abs !== absDir && !abs.startsWith(absDir + path.sep)) return send404(res);
  fs.stat(abs, (err, st) => {
    if (err || !st.isFile()) return send404(res);
    const ext = path.extname(abs).toLowerCase();
    const mime = MIME[ext] || 'application/octet-stream';
    const cc = ext === '.mp3' ? 'public, max-age=31536000, immutable' : 'max-age=600';
    res.writeHead(200, {
      'Content-Type': mime,
      'Cache-Control': cc,
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
  if (p === '/api/logout' && method === 'POST') return A(apiLogout);
  if (p === '/api/me' && method === 'GET') return A(apiMe);
  if (p === '/api/state' && method === 'GET') return A(apiStateGet);
  if (p === '/api/state/sync' && method === 'POST') return await A(apiStateSync);
  if (p === '/api/state/clear' && method === 'POST') return A(apiStateClear);
  if (p === '/api/admin/me' && method === 'GET') return A(apiAdminMe);
  if (p === '/api/admin/accounts' && method === 'GET') return A(apiAdminAccounts);
  if (p === '/api/admin/accounts' && method === 'POST') return await A(apiAdminCreate);
  if (p === '/api/admin/smtp' && method === 'GET') return A(apiAdminSmtpGet);
  if (p === '/api/admin/smtp' && method === 'PUT') return await A(apiAdminSmtpSet);
  let m = p.match(/^\/api\/admin\/accounts\/(\d+)$/);
  if (m && method === 'PUT') return await A((req, res) => apiAdminUpdate(req, res, Number(m[1])));
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
