"""brand9 server: static files + user accounts + SQLite-backed progress sync.

Zero third-party dependencies (stdlib only: http.server + sqlite3).
Endpoints:
  POST /api/send_code          {email} -> 6-digit verification email
  POST /api/register           {username, password, email, code}
  POST /api/login              {username, password} -> {token}
  POST /api/logout             (Bearer) -> invalidates token
  GET  /api/me                 (Bearer) -> {username}
  GET  /api/state              (Bearer) -> {key: {value, updated_at}}
  POST /api/state/sync         (Bearer) {entries:[{key, value, updated_at}]}
  POST /api/state/clear        (Bearer) -> wipe user state (keep account)

Auth: login issues a bearer token kept in memory (expires after 30 days).
Passwords: PBKDF2-HMAC-SHA256 with per-user random salt (120k iterations).
State rows are upserted per key; older timestamps never overwrite newer ones.

Email verification (anti mass-registration):
  code = 6 digits, valid for 5 minutes, resend allowed after 60s cooldown;
  a resend invalidates the previous code. SMTP settings are shared with
  dw-shop (DW_SHOP_SMTP_* from its .env, or the process environment).
"""
import http.server
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import sys
import threading
import time
import hashlib
from email.mime.text import MIMEText

PORT = int(os.environ.get("BRAND9_PORT", "8996"))
DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DIR, "brand9.db")

# Optional TLS: set BRAND9_TLS=1 (e.g. local Windows + ZeroTier + mkcert).
# Server-side deployment keeps plain HTTP by simply not setting it.
TLS_ENABLED = os.environ.get("BRAND9_TLS") == "1"
TLS_CERT = os.environ.get("BRAND9_CERT", os.path.join(DIR, "10.110.218.198+1.pem"))
TLS_KEY = os.environ.get("BRAND9_KEY", os.path.join(DIR, "10.110.218.198+1-key.pem"))

TOKEN_TTL = 30 * 24 * 3600  # 30 days
PBKDF2_ITER = 120_000

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
CODE_TTL = 300            # verification code valid for 5 minutes
RESEND_INTERVAL = 60      # min seconds between two sends to the same address


# ------------------------------------------------------- smtp (shared w/ dw-shop)
def _read_dwshop_env():
    """Read SMTP settings from dw-shop's .env so both apps share one credential."""
    env_path = os.path.join(DIR, "..", "fun", "dw-shop", ".env")
    out = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


_DWSHOP_ENV = _read_dwshop_env()
SMTP_HOST = os.environ.get("DW_SHOP_SMTP_HOST", _DWSHOP_ENV.get("DW_SHOP_SMTP_HOST", "smtp.qq.com"))
SMTP_PORT = int(os.environ.get("DW_SHOP_SMTP_PORT", _DWSHOP_ENV.get("DW_SHOP_SMTP_PORT", "465")))
SMTP_USER = os.environ.get("DW_SHOP_SMTP_USER", _DWSHOP_ENV.get("DW_SHOP_SMTP_USER", ""))
SMTP_PASSWORD = os.environ.get("DW_SHOP_SMTP_PASSWORD", _DWSHOP_ENV.get("DW_SHOP_SMTP_PASSWORD", ""))
MAIL_FROM = os.environ.get("DW_SHOP_MAIL_FROM", _DWSHOP_ENV.get("DW_SHOP_MAIL_FROM", "")) or SMTP_USER


def send_verification_email(email: str, code: str):
    """Send the 6-digit code email; returns None on success or an error message."""
    if not (SMTP_USER and SMTP_PASSWORD):
        return "SMTP 未配置（请检查 dw-shop/.env 的 DW_SHOP_SMTP_*）"
    body_html = f"""<div style="max-width:520px;margin:0 auto;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2328;background:#f6f7f9;padding:20px;">
  <div style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);">
    <div style="background:linear-gradient(135deg,#1a1f2e,#2d3550);color:#fff;padding:22px 26px;">
      <div style="font-size:19px;font-weight:700;">brand9<span style="color:#ffbca8;">·</span>雅思口语</div>
      <div style="font-size:13px;opacity:.85;margin-top:2px;">邮箱注册验证码</div>
    </div>
    <div style="padding:24px 26px;">
      <p style="margin:0 0 16px;font-size:14px;">你的注册验证码是：</p>
      <div style="margin:0 auto 18px;padding:20px;border:2px dashed #2d3550;border-radius:14px;text-align:center;">
        <div style="font-size:30px;font-weight:800;letter-spacing:6px;color:#1a1f2e;">{code}</div>
      </div>
      <p style="margin:0;font-size:13px;color:#6b7280;">验证码 <b>5 分钟内</b>有效。如果 1 分钟内重复发送，请以最新一封邮件为准。如非本人操作，请忽略本邮件。</p>
    </div>
    <div style="background:#fafbfc;padding:14px 26px;font-size:12px;color:#9ca3af;text-align:center;">
      brand9 · 雅思口语练习
    </div>
  </div>
</div>"""
    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = "【brand9】邮箱注册验证码"
    msg["From"] = MAIL_FROM
    msg["To"] = email
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return None
    except Exception as e:
        return "邮件发送失败: %s" % e

# in-memory token store: token -> {"user_id": int, "expires": float}
TOKENS = {}
TOKENS_LOCK = threading.Lock()


# ---------------------------------------------------------------- database
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT UNIQUE NOT NULL,
                pass_salt  TEXT NOT NULL,
                pass_hash  TEXT NOT NULL,
                created_at TEXT NOT NULL
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
            """
        )
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "email" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    print(f"[db] ready at {DB_PATH}")


# ------------------------------------------------------------------- crypto
def hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"),
        bytes.fromhex(salt_hex), PBKDF2_ITER
    ).hex()


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    return secrets.compare_digest(hash_password(password, salt_hex), expected_hash)


# ------------------------------------------------------------------- auth
def issue_token(user_id: int) -> str:
    token = secrets.token_hex(24)
    with TOKENS_LOCK:
        TOKENS[token] = {"user_id": user_id, "expires": time.time() + TOKEN_TTL}
    return token


def user_for_token(token: str):
    with TOKENS_LOCK:
        rec = TOKENS.get(token)
        if rec is None:
            return None
        if rec["expires"] < time.time():
            TOKENS.pop(token, None)
            return None
        return rec["user_id"]


# ---------------------------------------------------------------- handlers
class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DIR, **kw)

    # -- helpers ----------------------------------------------------------
    def end_headers(self):
        # Reference-answer mp3s are immutable: allow the browser to cache them
        # long-term (huge win for the 400+ audio files). Everything else that is
        # not an API response gets a short cache so edits appear quickly.
        path = self.path.split("?", 1)[0]
        if path.endswith(".mp3"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "max-age=600")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Never let logging break request handling: if stdout/stderr is gone
        # (e.g. this process was orphaned after its parent shell died), a
        # failed write must not crash the request thread.
        try:
            sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))
            sys.stdout.flush()
        except Exception:
            pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, error, status=400):
        self._json({"ok": False, "error": error}, status=status)

    def _auth(self):
        """Return user row or None (and send 401 when None)."""
        auth = self.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        uid = user_for_token(token) if token else None
        if uid is None:
            self._fail("未登录或登录已过期", status=401)
            return None
        with db() as conn:
            row = conn.execute(
                "SELECT id, username FROM users WHERE id = ?", (uid,)
            ).fetchone()
        if row is None:
            self._fail("用户不存在", status=401)
            return None
        return row

    # -- routes ------------------------------------------------------------
    def _api(self, method):
        path = self.path.split("?")[0]
        if path == "/api/register" and method == "POST":
            return self._api_register()
        if path == "/api/send_code" and method == "POST":
            return self._api_send_code()
        if path == "/api/login" and method == "POST":
            return self._api_login()
        if path == "/api/logout" and method == "POST":
            return self._api_logout()
        if path == "/api/me" and method == "GET":
            return self._api_me()
        if path == "/api/state" and method == "GET":
            return self._api_state_get()
        if path == "/api/state/sync" and method == "POST":
            return self._api_state_sync()
        if path == "/api/state/clear" and method == "POST":
            return self._api_state_clear()
        self._fail("未知接口: %s %s" % (method, path), status=404)

    def _api_send_code(self):
        """Send a 6-digit code; 60s cooldown; resend invalidates the old code."""
        data = self._read_json()
        email = str(data.get("email") or "").strip().lower()
        if not EMAIL_RE.match(email):
            return self._fail("邮箱格式不正确")
        now = int(time.time())
        with db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                return self._fail("该邮箱已被注册", status=409)
            row = conn.execute(
                "SELECT sent_at FROM email_codes WHERE email = ?", (email,)
            ).fetchone()
            if row is not None:
                wait = RESEND_INTERVAL - (now - row["sent_at"])
                if wait > 0:
                    return self._json(
                        {"ok": False, "error": f"发送太频繁，请 {wait} 秒后再试", "wait": wait},
                        status=429,
                    )
        code = "%06d" % secrets.randbelow(1000000)
        with db() as conn:
            conn.execute("DELETE FROM email_codes WHERE email = ?", (email,))
            conn.execute(
                "INSERT INTO email_codes (email, code, sent_at, expires_at) VALUES (?,?,?,?)",
                (email, code, now, now + CODE_TTL),
            )
        err = send_verification_email(email, code)
        if err is not None:
            with db() as conn:
                conn.execute("DELETE FROM email_codes WHERE email = ?", (email,))
            return self._fail(err, status=500)
        return self._json({"ok": True, "wait": RESEND_INTERVAL, "ttl": CODE_TTL})

    def _api_register(self):
        data = self._read_json()
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        email = str(data.get("email") or "").strip().lower()
        code = str(data.get("code") or "").strip()
        if not (3 <= len(username) <= 32):
            return self._fail("用户名需为 3-32 个字符")
        if not (6 <= len(password) <= 128):
            return self._fail("密码需为 6-128 个字符")
        if not EMAIL_RE.match(email):
            return self._fail("邮箱格式不正确")
        now = int(time.time())
        with db() as conn:
            if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                return self._fail("该邮箱已被注册", status=409)
            row = conn.execute(
                "SELECT code, expires_at FROM email_codes WHERE email = ?", (email,)
            ).fetchone()
        if row is None or row["expires_at"] < now:
            return self._fail("验证码不存在或已过期，请先获取验证码")
        if row["code"] != code:
            return self._fail("验证码错误")
        salt = secrets.token_hex(16)
        pw_hash = hash_password(password, salt)
        try:
            with db() as conn:
                cur = conn.execute(
                    "INSERT INTO users (username, pass_salt, pass_hash, created_at, email) VALUES (?,?,?,?,?)",
                    (username, salt, pw_hash, time.strftime("%Y-%m-%d %H:%M:%S"), email),
                )
                user_id = cur.lastrowid
                conn.execute("DELETE FROM email_codes WHERE email = ?", (email,))
        except sqlite3.IntegrityError:
            return self._fail("用户名已被注册", status=409)
        token = issue_token(user_id)
        return self._json({"ok": True, "token": token, "username": username})

    def _api_login(self):
        data = self._read_json()
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        with db() as conn:
            row = conn.execute(
                "SELECT id, username, pass_salt, pass_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None or not verify_password(password, row["pass_salt"], row["pass_hash"]):
            return self._fail("用户名或密码错误", status=401)
        token = issue_token(row["id"])
        return self._json({"ok": True, "token": token, "username": row["username"]})

    def _api_logout(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            with TOKENS_LOCK:
                TOKENS.pop(auth[7:], None)
        return self._json({"ok": True})

    def _api_me(self):
        user = self._auth()
        if user is None:
            return
        return self._json({"ok": True, "username": user["username"]})

    def _api_state_get(self):
        user = self._auth()
        if user is None:
            return
        with db() as conn:
            rows = conn.execute(
                "SELECT key, value, updated_at FROM user_state WHERE user_id = ?",
                (user["id"],),
            ).fetchall()
        state = {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}
        return self._json({"ok": True, "state": state})

    def _api_state_sync(self):
        user = self._auth()
        if user is None:
            return
        data = self._read_json()
        entries = data.get("entries")
        if not isinstance(entries, list):
            return self._fail("entries 必须为数组")
        saved = 0
        with db() as conn:
            for e in entries:
                key = str(e.get("key") or "")
                value = e.get("value")
                ts = int(e.get("updated_at") or 0)
                if not key or value is None:
                    continue
                value = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
                cur = conn.execute(
                    """INSERT INTO user_state (user_id, key, value, updated_at)
                       VALUES (?,?,?,?)
                       ON CONFLICT(user_id, key) DO UPDATE SET
                         value      = excluded.value,
                         updated_at = excluded.updated_at
                       WHERE excluded.updated_at >= user_state.updated_at""",
                    (user["id"], key, value, ts),
                )
                if cur.rowcount > 0:
                    saved += 1
        return self._json({"ok": True, "saved": saved})

    def _api_state_clear(self):
        user = self._auth()
        if user is None:
            return
        with db() as conn:
            conn.execute("DELETE FROM user_state WHERE user_id = ?", (user["id"],))
        return self._json({"ok": True})

    # -- HTTP verbs ---------------------------------------------------------
    def do_GET(self):
        if self.path.split("?")[0].startswith("/api/"):
            return self._api("GET")
        return super().do_GET()

    def do_POST(self):
        return self._api("POST")


if __name__ == "__main__":
    init_db()
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    if TLS_ENABLED:
        if not (os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY)):
            print(f"ERROR: BRAND9_TLS=1 but cert/key not found:\n  {TLS_CERT}\n  {TLS_KEY}")
            sys.exit(1)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(TLS_CERT, TLS_KEY)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        print(f"Serving {DIR} on https://0.0.0.0:{PORT}")
    else:
        print(f"Serving {DIR} on http://0.0.0.0:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
