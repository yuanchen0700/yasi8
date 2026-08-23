import os
import secrets
import smtplib
import sqlite3
import uuid
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from html import escape
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dwshop.db"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env(BASE_DIR / ".env")

from helpers import cover_class, cover_emoji

app = Flask(__name__)
app.jinja_env.filters["cover_class"] = cover_class
app.jinja_env.filters["cover_emoji"] = cover_emoji
app.secret_key = os.environ.get("DW_SHOP_SECRET", "dw-shop-dev-secret-change-me")
ADMIN_PASSWORD = os.environ.get("DW_SHOP_ADMIN_PASSWORD", "dwshop123")


def _ensure_admin_path():
    """管理后台路径：优先用 DW_SHOP_ADMIN_PATH，未设置则随机生成 8 位并持久化到 .env。"""
    path = os.environ.get("DW_SHOP_ADMIN_PATH", "").strip().strip("/")
    if path and path.isalnum():
        return path
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    path = "".join(secrets.choice(alphabet) for _ in range(8))
    env_file = BASE_DIR / ".env"
    with open(env_file, "a", encoding="utf-8") as f:
        f.write(f"DW_SHOP_ADMIN_PATH={path}\n")
    os.environ["DW_SHOP_ADMIN_PATH"] = path
    return path


ADMIN_PATH = _ensure_admin_path()
ADMIN_PREFIX = f"/{ADMIN_PATH}"

SMTP_HOST = os.environ.get("DW_SHOP_SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.environ.get("DW_SHOP_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("DW_SHOP_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("DW_SHOP_SMTP_PASSWORD", "")
MAIL_FROM = os.environ.get("DW_SHOP_MAIL_FROM", "") or SMTP_USER
MAIL_CC = os.environ.get("DW_SHOP_MAIL_CC", "2551502388@qq.com")

ALLOWED_COVER_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
CATEGORIES = ["笔记", "服务"]


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subtitle TEXT DEFAULT '',
                category TEXT NOT NULL DEFAULT '笔记',
                price REAL NOT NULL DEFAULT 0,
                cover TEXT DEFAULT '',
                description TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                contact TEXT NOT NULL,
                message TEXT DEFAULT '',
                qty INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT '待处理',
                remark TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                is_cover INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                code TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'unused',
                order_id INTEGER,
                email TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                issued_at TEXT
            );
            """
        )
        try:
            db.execute("ALTER TABLE orders ADD COLUMN wechat TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        migrate_cover(db)
    seed()


def migrate_cover(db):
    rows = db.execute("SELECT id, cover FROM products WHERE cover != ''").fetchall()
    for row in rows:
        exists = db.execute(
            "SELECT COUNT(*) FROM product_images WHERE product_id = ?", (row["id"],)
        ).fetchone()[0]
        if exists == 0:
            db.execute(
                "INSERT INTO product_images (product_id, url, is_cover, created_at) "
                "VALUES (?, ?, 1, ?)",
                (row["id"], row["cover"], now()),
            )
    db.commit()


def product_images(db, pid):
    return db.execute(
        "SELECT * FROM product_images WHERE product_id = ? ORDER BY is_cover DESC, id",
        (pid,),
    ).fetchall()


def seed():
    with sqlite3.connect(DB_PATH) as db:
        count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            samples = [
                (
                    "Python 入门笔记",
                    "写给零基础的完整教程",
                    "笔记",
                    19.9,
                    "",
                    "包含 Python 基础语法、常用库与实战项目，共 12 章。购买后请联系我获取笔记文件。",
                    1,
                ),
                (
                    "雅思口语高分模板",
                    "Part1/2/3 逐题示例",
                    "笔记",
                    29.9,
                    "",
                    "覆盖雅思口语全题型，含地道表达与高分句式，配合每日练习效果更佳。",
                    1,
                ),
                (
                    "简历修改服务",
                    "一对一沟通，48 小时内交付",
                    "服务",
                    99.0,
                    "",
                    "资深求职者一对一帮你改简历，包含内容梳理与排版优化，48 小时内交付返稿。",
                    1,
                ),
            ]
            db.executemany(
                "INSERT INTO products (title, subtitle, category, price, cover, description, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(t, s, c, p, cv, d, a, now()) for t, s, c, p, cv, d, a in samples],
            )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


def gen_voucher_code():
    return "DW-" + secrets.token_hex(4).upper()


def qr_block(cid, img_path, label, hint):
    if img_path.exists():
        return (
            f'<div style="margin:10px auto;width:200px;padding:12px;border:1px solid #eceef1;'
            f'border-radius:12px;background:#fafbfc;">'
            f'<p style="margin:0 0 8px;font-size:13px;color:#111;font-weight:700;">{label}</p>'
            f'<img src="cid:{cid}" alt="{label}" style="width:160px;height:160px;border-radius:8px;display:block;margin:0 auto;">'
            f'<p style="margin:8px 0 0;font-size:12px;color:#888;">{hint}</p>'
            f"</div>"
        )
    return (
        f'<div style="margin:10px auto;width:200px;padding:16px;border:1px dashed #cbd5e1;'
        f'border-radius:12px;background:#f8fafc;text-align:center;">'
        f'<p style="margin:0;font-size:13px;color:#111;font-weight:700;">{label}</p>'
        f'<p style="margin:6px 0 0;font-size:12px;color:#94a3b8;">{hint}</p>'
        f"</div>"
    )


def send_order_email(order, product):
    email = (order["contact"] or "").strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        return False, "买家未留邮箱，跳过发送"
    if not (SMTP_USER and SMTP_PASSWORD):
        return False, "SMTP 未配置"
    subject = f"【DW Shop】订单确认 #{order['id']}"

    title = escape(product["title"])
    desc = escape(product["description"] or "（店主会在沟通时提供详细内容）")
    note = escape(order["message"] or "无")
    name = escape(order["name"])
    price = "%.2f" % product["price"]

    wechat_qr = BASE_DIR / "static" / "qrcodes" / "wechat_qr.png"
    gzh_qr = BASE_DIR / "static" / "qrcodes" / "gzh_qr.png"

    wechat_block = qr_block(
        "wechat", wechat_qr, "微信扫码支付", "长按识别二维码，添加店主微信完成付款即可发货"
    )
    gzh_block = qr_block(
        "gzh", gzh_qr, "公众号（关注最新内容）", "关注后第一时间获取新品与优惠"
    )

    body_html = f"""<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2328;background:#f6f7f9;padding:20px;">
  <div style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);">
    <div style="background:#2563eb;color:#ffffff;padding:22px 26px;">
      <div style="font-size:20px;font-weight:700;">DW<span style="color:#fbbf24;">.</span>Shop</div>
      <div style="font-size:13px;opacity:.9;margin-top:2px;">订单确认 · #{order['id']}</div>
    </div>
    <div style="padding:24px 26px;">
      <p style="margin:0 0 14px;">你好 <b>{name}</b>，感谢你在 DW Shop 拍下商品，以下是订单详情：</p>

      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr>
          <td style="padding:8px 0;color:#6b7280;width:90px;">商品</td>
          <td style="padding:8px 0;"><b>{title}</b></td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#6b7280;">数量</td>
          <td style="padding:8px 0;">{order['qty']}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#6b7280;">金额</td>
          <td style="padding:8px 0;"><span style="color:#2563eb;font-weight:800;font-size:18px;">¥{price}</span>（线下支付）</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#6b7280;vertical-align:top;">留言</td>
          <td style="padding:8px 0;">{note}</td>
        </tr>
      </table>

      <div style="margin-top:18px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;">
        <p style="margin:0 0 4px;font-size:14px;font-weight:700;">📦 商品介绍</p>
        <p style="margin:0;font-size:14px;color:#374151;white-space:pre-wrap;">{desc}</p>
      </div>

      <p style="margin:20px 0 6px;font-size:15px;font-weight:700;">💳 如何完成购买？</p>
      <p style="margin:0 0 4px;font-size:14px;color:#374151;">请使用微信扫描下方二维码，添加店主微信，<b>完成付款后即可发货</b>。</p>
      <p style="margin:0 0 10px;font-size:13px;color:#94a3b8;">付款时请备注订单号 #{order['id']}，方便店主核对。</p>

      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
        <tr>
          <td align="center" width="50%" style="padding:0 6px;">{wechat_block}</td>
          <td align="center" width="50%" style="padding:0 6px;">{gzh_block}</td>
        </tr>
      </table>

      <p style="margin:20px 0 0;font-size:13px;color:#94a3b8;">如有任何问题，直接回复本邮件即可，店主会尽快处理。</p>
    </div>
    <div style="background:#fafbfc;padding:14px 26px;font-size:12px;color:#9ca3af;text-align:center;">
      DW Shop · 出售笔记与有趣的服务
    </div>
  </div>
</div>"""

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = email
    if MAIL_CC:
        msg["Cc"] = MAIL_CC
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    for cid, path in (("wechat", wechat_qr), ("gzh", gzh_qr)):
        if path.exists():
            with open(path, "rb") as f:
                part = MIMEImage(f.read())
            part.add_header("Content-ID", f"<{cid}>")
            part.add_header("Content-Disposition", "inline", filename=path.name)
            msg.attach(part)
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True, "邮件已发送"
    except Exception as e:
        return False, f"邮件发送失败: {e}"


def send_voucher_email(voucher, product, email):
    email = (email or "").strip()
    if not email or "@" not in email:
        return False, "未提供有效的接收邮箱"
    if not (SMTP_USER and SMTP_PASSWORD):
        return False, "SMTP 未配置"
    subject = f"【DW Shop】您的卡券 {voucher['code']}"
    title = escape(product["title"])
    code = escape(voucher["code"])
    note = escape(voucher["note"] or "")
    wechat_qr = BASE_DIR / "static" / "qrcodes" / "wechat_qr.png"
    wechat_block = qr_block(
        "wechat", wechat_qr, "微信扫码支付", "长按识别二维码，添加店主微信完成付款即可发货"
    )

    body_html = f"""<div style="max-width:600px;margin:0 auto;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#1f2328;background:#f6f7f9;padding:20px;">
  <div style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);">
    <div style="background:#7c3aed;color:#ffffff;padding:22px 26px;">
      <div style="font-size:20px;font-weight:700;">DW<span style="color:#fbbf24;">.</span>Shop</div>
      <div style="font-size:13px;opacity:.9;margin-top:2px;">卡券 · {title}</div>
    </div>
    <div style="padding:24px 26px;">
      <p style="margin:0 0 14px;">你好，恭喜你获得一张 <b>{title}</b> 卡券：</p>

      <div style="margin:18px auto;padding:22px;border:2px dashed #7c3aed;border-radius:14px;text-align:center;background:#faf5ff;">
        <div style="font-size:12px;color:#8b5cf6;letter-spacing:2px;margin-bottom:8px;">DW SHOP 卡券码</div>
        <div style="font-size:26px;font-weight:800;letter-spacing:3px;color:#4c1d95;">{code}</div>
      </div>

      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;font-size:14px;color:#374151;">
        <p style="margin:0 0 4px;font-weight:700;">如何使用？</p>
        <p style="margin:0;white-space:pre-wrap;">付款后向店主出示此卡券码即可核销使用{ '；备注：' + note if note else '' }。请妥善保管，卡券码为唯一凭证。</p>
      </div>

      <p style="margin:20px 0 6px;font-size:15px;font-weight:700;">💳 还没付款？</p>
      <p style="margin:0 0 10px;font-size:14px;color:#374151;">请微信扫描下方二维码添加店主，完成付款后即可使用卡券。</p>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
        <tr>
          <td align="center" style="padding:0;">{wechat_block}</td>
        </tr>
      </table>

      <p style="margin:20px 0 0;font-size:13px;color:#94a3b8;">如有问题直接回复本邮件即可，店主会尽快处理。</p>
    </div>
    <div style="background:#fafbfc;padding:14px 26px;font-size:12px;color:#9ca3af;text-align:center;">
      DW Shop · 出售笔记与有趣的服务
    </div>
  </div>
</div>"""

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = MAIL_FROM
    msg["To"] = email
    if MAIL_CC:
        msg["Cc"] = MAIL_CC
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    if wechat_qr.exists():
        with open(wechat_qr, "rb") as f:
            part = MIMEImage(f.read())
        part.add_header("Content-ID", "<wechat>")
        part.add_header("Content-Disposition", "inline", filename=wechat_qr.name)
        msg.attach(part)
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True, "邮件已发送"
    except Exception as e:
        return False, f"邮件发送失败: {e}"


@app.route("/")
def index():
    db = get_db()
    products = [dict(p) for p in db.execute(
        "SELECT * FROM products WHERE active = 1 ORDER BY category, id DESC"
    ).fetchall()]
    for p in products:
        p["_images"] = [dict(i) for i in product_images(db, p["id"])]
        if not p["_images"] and p["cover"]:
            p["_images"] = [{"url": p["cover"], "is_cover": 1, "id": 0}]
    return render_template("index.html", products=products, categories=CATEGORIES)


@app.route("/product/<int:pid>")
def product(pid):
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id = ? AND active = 1", (pid,)).fetchone()
    if row is None:
        abort(404)
    images = [dict(i) for i in product_images(db, pid)]
    if not images and row["cover"]:
        images = [{"url": row["cover"], "is_cover": 1, "id": 0}]
    return render_template("product.html", product=row, images=images)


@app.route("/product/<int:pid>/order", methods=["POST"])
def place_order(pid):
    db = get_db()
    product_row = db.execute(
        "SELECT * FROM products WHERE id = ? AND active = 1", (pid,)
    ).fetchone()
    if product_row is None:
        abort(404)
    name = request.form.get("name", "").strip()
    email = request.form.get("contact", "").strip()
    wechat = request.form.get("wechat", "").strip()
    message = request.form.get("message", "").strip()
    try:
        qty = int(request.form.get("qty", "1"))
    except ValueError:
        qty = 1
    if qty < 1:
        qty = 1
    if not name:
        flash("请填写称呼", "error")
        return redirect(url_for("product", pid=pid))
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        flash("请填写有效的邮箱（用于接收订单和卡券信息）", "error")
        return redirect(url_for("product", pid=pid))
    db.execute(
        "INSERT INTO orders (product_id, name, contact, wechat, message, qty, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (pid, name, email, wechat, message, qty, now()),
    )
    db.commit()
    order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    order_row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    ok, info = send_order_email(order_row, product_row)
    if not ok:
        db.execute("UPDATE orders SET remark = ? WHERE id = ?", (info, order_id))
        db.commit()
    return redirect(url_for("order_done", oid=order_id))


@app.route("/order/<int:oid>/done")
def order_done(oid):
    db = get_db()
    order_row = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if order_row is None:
        abort(404)
    product_row = db.execute(
        "SELECT * FROM products WHERE id = ?", (order_row["product_id"],)
    ).fetchone()
    return render_template("order_done.html", order=order_row, product=product_row)


@app.route("/order/query", methods=["GET", "POST"])
def order_query():
    results = None
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or "@" not in email:
            flash("请输入有效的邮箱", "error")
        else:
            db = get_db()
            results = db.execute(
                "SELECT o.*, p.title AS product_title FROM orders o "
                "JOIN products p ON p.id = o.product_id "
                "WHERE lower(o.contact) = ? AND o.created_at >= date('now', '-62 days') "
                "ORDER BY o.id DESC",
                (email,),
            ).fetchall()
            if not results:
                flash("最近 62 天没有找到该邮箱的订单", "error")
    return render_template("order_query.html", results=results, email=email)


# ---------------- admin ----------------

@app.route(ADMIN_PREFIX + "/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            session["admin_token"] = uuid.uuid4().hex
            return redirect(url_for("admin_dashboard"))
        flash("密码错误", "error")
    return render_template("admin_login.html")


@app.route(ADMIN_PREFIX + "/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route(ADMIN_PREFIX)
@login_required
def admin_dashboard():
    db = get_db()
    orders = db.execute(
        "SELECT o.*, p.title AS product_title FROM orders o "
        "JOIN products p ON p.id = o.product_id ORDER BY o.id DESC"
    ).fetchall()
    stats = {
        "orders": db.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"],
        "pending": db.execute(
            "SELECT COUNT(*) c FROM orders WHERE status = '待处理'"
        ).fetchone()["c"],
        "products": db.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
    }
    return render_template("admin.html", orders=orders, stats=stats)


@app.route(ADMIN_PREFIX + "/order/<int:oid>/status", methods=["POST"])
@login_required
def admin_order_status(oid):
    status = request.form.get("status", "待处理")
    db = get_db()
    order = db.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if order is None:
        abort(404)
    prev = order["status"]
    db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, oid))
    db.commit()
    if status == "已付款" and prev != "已付款":
        voucher = db.execute(
            "SELECT * FROM vouchers WHERE product_id = ? AND status = 'unused' ORDER BY id LIMIT 1",
            (order["product_id"],),
        ).fetchone()
        if voucher:
            product = db.execute(
                "SELECT * FROM products WHERE id = ?", (order["product_id"],)
            ).fetchone()
            email = order["contact"]
            db.execute(
                "UPDATE vouchers SET status = 'issued', email = ?, order_id = ?, issued_at = ? WHERE id = ?",
                (email, oid, now(), voucher["id"]),
            )
            db.commit()
            ok, info = send_voucher_email(voucher, product, email)
            if ok:
                flash(f"订单已标记已付款，卡券 {voucher['code']} 已发送至 {email}", "success")
            else:
                flash(f"订单已标记已付款，卡券 {voucher['code']} 已分配至 {email}，但邮件发送失败：{info}", "error")
        else:
            flash(
                "订单已标记已付款，但该商品没有未发放的卡券，请先在「卡券」管理中生成。",
                "error",
            )
    return redirect(url_for("admin_dashboard"))


@app.route(ADMIN_PREFIX + "/order/<int:oid>/remark", methods=["POST"])
@login_required
def admin_order_remark(oid):
    remark = request.form.get("remark", "").strip()
    db = get_db()
    db.execute("UPDATE orders SET remark = ? WHERE id = ?", (remark, oid))
    db.commit()
    return redirect(url_for("admin_dashboard"))


@app.route(ADMIN_PREFIX + "/vouchers")
@login_required
def admin_vouchers():
    db = get_db()
    vouchers = db.execute(
        "SELECT v.*, p.title AS product_title FROM vouchers v "
        "JOIN products p ON p.id = v.product_id ORDER BY v.id DESC"
    ).fetchall()
    products = db.execute("SELECT id, title FROM products ORDER BY id DESC").fetchall()
    stats = {
        "total": len(vouchers),
        "unused": sum(1 for v in vouchers if v["status"] == "unused"),
        "issued": sum(1 for v in vouchers if v["status"] == "issued"),
        "used": sum(1 for v in vouchers if v["status"] == "used"),
    }
    return render_template(
        "admin_vouchers.html", vouchers=vouchers, products=products, stats=stats
    )


@app.route(ADMIN_PREFIX + "/vouchers/generate", methods=["POST"])
@login_required
def admin_vouchers_generate():
    try:
        pid = int(request.form.get("product_id", "0"))
    except ValueError:
        pid = 0
    try:
        count = int(request.form.get("count", "1"))
    except ValueError:
        count = 1
    if count < 1:
        count = 1
    if count > 100:
        count = 100
    note = request.form.get("note", "").strip()
    db = get_db()
    exists = db.execute("SELECT id FROM products WHERE id = ?", (pid,)).fetchone()
    if not exists:
        flash("请选择有效的商品", "error")
        return redirect(url_for("admin_vouchers"))
    codes = []
    while len(codes) < count:
        code = gen_voucher_code()
        dup = db.execute("SELECT 1 FROM vouchers WHERE code = ?", (code,)).fetchone()
        if not dup:
            codes.append(code)
    db.executemany(
        "INSERT INTO vouchers (product_id, code, status, note, created_at) "
        "VALUES (?, ?, 'unused', ?, ?)",
        [(pid, c, note, now()) for c in codes],
    )
    db.commit()
    flash(f"已生成 {len(codes)} 张卡券", "success")
    return redirect(url_for("admin_vouchers"))


@app.route(ADMIN_PREFIX + "/vouchers/<int:vid>/issue", methods=["POST"])
@login_required
def admin_voucher_issue(vid):
    db = get_db()
    v = db.execute("SELECT * FROM vouchers WHERE id = ?", (vid,)).fetchone()
    if v is None:
        abort(404)
    email = request.form.get("email", "").strip()
    order_id = request.form.get("order_id", "").strip() or None
    if not email or "@" not in email:
        flash("请输入有效的发放邮箱", "error")
        return redirect(url_for("admin_vouchers"))
    product = db.execute(
        "SELECT * FROM products WHERE id = ?", (v["product_id"],)
    ).fetchone()
    ok, info = send_voucher_email(v, product, email)
    if not ok:
        flash(f"卡券发放失败：{info}", "error")
        return redirect(url_for("admin_vouchers"))
    db.execute(
        "UPDATE vouchers SET status = 'issued', email = ?, order_id = ?, issued_at = ? "
        "WHERE id = ?",
        (email, order_id, now(), vid),
    )
    db.commit()
    flash(f"卡券 {v['code']} 已发放至 {email}", "success")
    return redirect(url_for("admin_vouchers"))


@app.route(ADMIN_PREFIX + "/products")
@login_required
def admin_products():
    db = get_db()
    products = db.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    return render_template("admin_products.html", products=products, categories=CATEGORIES)


@app.route(ADMIN_PREFIX + "/product/new", methods=["GET", "POST"])
@login_required
def admin_product_new():
    if request.method == "POST":
        return _save_product(None)
    return render_template(
        "admin_product_edit.html", product=None, categories=CATEGORIES, images=[]
    )


@app.route(ADMIN_PREFIX + "/product/<int:pid>/edit", methods=["GET", "POST"])
@login_required
def admin_product_edit(pid):
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        return _save_product(pid)
    images = product_images(db, pid)
    return render_template(
        "admin_product_edit.html", product=row, categories=CATEGORIES, images=images
    )


def _save_product(pid):
    title = request.form.get("title", "").strip()
    if not title:
        flash("标题不能为空", "error")
        return redirect(url_for("admin_product_new") if pid is None else url_for("admin_product_edit", pid=pid))
    subtitle = request.form.get("subtitle", "").strip()
    category = request.form.get("category", "笔记")
    try:
        price = float(request.form.get("price", "0"))
    except ValueError:
        price = 0
    cover = request.form.get("cover", "").strip()
    description = request.form.get("description", "").strip()
    active = 1 if request.form.get("active") else 0
    db = get_db()
    if pid is None:
        db.execute(
            "INSERT INTO products (title, subtitle, category, price, cover, description, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, subtitle, category, price, cover, description, active, now()),
        )
    else:
        db.execute(
            "UPDATE products SET title = ?, subtitle = ?, category = ?, price = ?, "
            "cover = ?, description = ?, active = ? WHERE id = ?",
            (title, subtitle, category, price, cover, description, active, pid),
        )
    db.commit()
    return redirect(url_for("admin_products"))


@app.route(ADMIN_PREFIX + "/product/<int:pid>/toggle", methods=["POST"])
@login_required
def admin_product_toggle(pid):
    db = get_db()
    db.execute(
        "UPDATE products SET active = 1 - active WHERE id = ?",
        (pid,),
    )
    db.commit()
    return redirect(url_for("admin_products"))


def _save_cover_files(db, pid, files):
    if not files:
        return
    has_cover = db.execute(
        "SELECT COUNT(*) FROM product_images WHERE product_id = ? AND is_cover = 1",
        (pid,),
    ).fetchone()[0]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = 0
    for f in files:
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in ALLOWED_COVER_EXT:
            continue
        fname = f"p{pid}_{uuid.uuid4().hex[:8]}.{ext}"
        f.save(UPLOAD_DIR / fname)
        url = url_for("static", filename=f"uploads/{fname}")
        db.execute(
            "INSERT INTO product_images (product_id, url, is_cover, created_at) "
            "VALUES (?, ?, ?, ?)",
            (pid, url, 1 if not has_cover else 0, now()),
        )
        has_cover = True
        saved += 1
    return saved


@app.route(ADMIN_PREFIX + "/product/<int:pid>/cover", methods=["POST"])
@login_required
def admin_product_cover(pid):
    db = get_db()
    row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if row is None:
        abort(404)
    files = request.files.getlist("covers")
    if not files or all(not f.filename for f in files):
        flash("请选择要上传的图片", "error")
        return redirect(url_for("admin_product_edit", pid=pid))
    saved = _save_cover_files(db, pid, files)
    db.commit()
    if saved:
        flash(f"已上传 {saved} 张图片", "success")
    else:
        flash("没有可上传的图片（仅支持 png / jpg / jpeg / gif / webp）", "error")
    return redirect(url_for("admin_product_edit", pid=pid))


@app.route(ADMIN_PREFIX + "/product/<int:pid>/image/<int:img_id>/delete", methods=["POST"])
@login_required
def admin_product_image_delete(pid, img_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM product_images WHERE id = ? AND product_id = ?", (img_id, pid)
    ).fetchone()
    if row is None:
        abort(404)
    db.execute("DELETE FROM product_images WHERE id = ?", (img_id,))
    left = db.execute(
        "SELECT COUNT(*) FROM product_images WHERE product_id = ? AND is_cover = 1",
        (pid,),
    ).fetchone()[0]
    if left == 0:
        next_img = db.execute(
            "SELECT id FROM product_images WHERE product_id = ? ORDER BY id LIMIT 1",
            (pid,),
        ).fetchone()
        if next_img:
            db.execute(
                "UPDATE product_images SET is_cover = 1 WHERE id = ?", (next_img["id"],)
            )
    db.commit()
    flash("已删除该图片", "success")
    return redirect(url_for("admin_product_edit", pid=pid))


@app.route(ADMIN_PREFIX + "/product/<int:pid>/image/<int:img_id>/cover", methods=["POST"])
@login_required
def admin_product_image_cover(pid, img_id):
    db = get_db()
    exists = db.execute(
        "SELECT id FROM product_images WHERE id = ? AND product_id = ?", (img_id, pid)
    ).fetchone()
    if exists is None:
        abort(404)
    db.execute(
        "UPDATE product_images SET is_cover = 0 WHERE product_id = ?", (pid,)
    )
    db.execute("UPDATE product_images SET is_cover = 1 WHERE id = ?", (img_id,))
    db.commit()
    flash("已设为封面", "success")
    return redirect(url_for("admin_product_edit", pid=pid))


@app.route("/healthz")
def healthz():
    return "ok"


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="页面不存在"), 404


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 8997))
    app.run(host="0.0.0.0", port=port, debug=False)
