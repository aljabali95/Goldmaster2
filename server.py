#!/usr/bin/env python3
"""
غولد ماستر - Gold Master Financial Server
Flask + SQLite backend for the mobile banking app
"""

import os
import json
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, send_file

app = Flask(__name__, static_folder='public')

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'goldmaster.db'))
SECRET_KEY = os.environ.get('SECRET_KEY', 'goldmaster-secret-haleb-2026')

# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_pw(pw):
    return hashlib.sha256((pw + SECRET_KEY).encode()).hexdigest()

def make_token(user_id):
    import time
    payload = f"{user_id}:{int(time.time())+86400}"
    sig = hashlib.sha256((payload + SECRET_KEY).encode()).hexdigest()[:16]
    return f"{payload}:{sig}"

def verify_token(token):
    import time
    try:
        parts = token.split(":")
        user_id, exp, sig = parts[0], parts[1], parts[2]
        if int(exp) < int(time.time()):
            return None
        expected = hashlib.sha256((f"{user_id}:{exp}" + SECRET_KEY).encode()).hexdigest()[:16]
        if sig != expected:
            return None
        return user_id
    except:
        return None

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        phone       TEXT UNIQUE NOT NULL,
        password    TEXT NOT NULL,
        pin         TEXT NOT NULL,
        balance     REAL DEFAULT 0,
        currency    TEXT DEFAULT 'ل.س',
        city        TEXT DEFAULT '',
        status      TEXT DEFAULT 'نشط',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user   TEXT NOT NULL,
        to_user     TEXT NOT NULL,
        amount      REAL NOT NULL,
        note        TEXT DEFAULT '',
        type        TEXT DEFAULT 'transfer',
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(from_user) REFERENCES users(id),
        FOREIGN KEY(to_user)   REFERENCES users(id)
    )''')
    # Add type column if upgrading old DB
    try:
        c.execute("ALTER TABLE transactions ADD COLUMN type TEXT DEFAULT 'transfer'")
    except:
        pass

    # Seed demo accounts if empty
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        demo_users = [
            ("GM001234", "أحمد محمد الحلبي",  "0911234567", hash_pw("1234"), hash_pw("1234"), 250000, "حلب - الباب"),
            ("GM005678", "سارة أحمد الزعبي",   "0922345678", hash_pw("5678"), hash_pw("5678"), 180000, "حلب"),
            ("GM009999", "محمد سعيد الرفاعي",  "0933456789", hash_pw("9999"), hash_pw("9999"), 500000, "الباب"),
        ]
        for u in demo_users:
            c.execute(
                "INSERT OR IGNORE INTO users (id,name,phone,password,pin,balance,city) VALUES (?,?,?,?,?,?,?)",
                u
            )

        # Seed demo transactions
        demo_tx = [
            ("GM005678", "GM001234", 50000, "دفعة شهرية"),
            ("GM001234", "GM005678", 25000, "تحويل"),
            ("GM009999", "GM001234", 120000, "راتب"),
            ("GM001234", "GM009999", 15000, "فاتورة كهرباء"),
        ]
        for t in demo_tx:
            c.execute(
                "INSERT INTO transactions (from_user,to_user,amount,note) VALUES (?,?,?,?)",
                t
            )

    conn.commit()
    conn.close()
    print("✅ قاعدة البيانات جاهزة")

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def auth_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        user_id = verify_token(token)
        if not user_id:
            return jsonify({"error": "غير مصرح"}), 401
        return f(user_id, *args, **kwargs)
    return wrapper

def generate_user_id():
    conn = get_db()
    while True:
        uid = "GM" + str(secrets.randbelow(900000) + 100000)
        row = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            conn.close()
            return uid

def fmt_date(dt_str):
    try:
        dt = datetime.strptime(dt_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y/%m/%d - %H:%M")
    except:
        return dt_str

# ─────────────────────────────────────────────
# ROUTES — AUTH
# ─────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    acc  = str(data.get("account", "")).strip().upper()
    pw   = str(data.get("password", ""))

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE id=? AND password=?",
        (acc, hash_pw(pw))
    ).fetchone()
    conn.close()

    if not user:
        return jsonify({"error": "رقم الحساب أو كلمة المرور غير صحيحة"}), 401

    token = make_token(user["id"])
    return jsonify({
        "token": token,
        "user": {
            "id":       user["id"],
            "name":     user["name"],
            "phone":    user["phone"],
            "balance":  user["balance"],
            "currency": user["currency"],
            "city":     user["city"],
            "status":   user["status"],
        }
    })

# ─────────────────────────────────────────────
# ROUTES — USER
# ─────────────────────────────────────────────
@app.route("/api/me", methods=["GET"])
@auth_required
def get_me(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not user:
        return jsonify({"error": "مستخدم غير موجود"}), 404
    return jsonify({
        "id":       user["id"],
        "name":     user["name"],
        "phone":    user["phone"],
        "balance":  user["balance"],
        "currency": user["currency"],
        "city":     user["city"],
        "status":   user["status"],
    })

@app.route("/api/lookup", methods=["GET"])
@auth_required
def lookup_user(user_id):
    q = request.args.get("q","").strip().upper()
    ph = request.args.get("phone","").strip()
    conn = get_db()
    if q:
        user = conn.execute("SELECT id,name,city,phone FROM users WHERE id=?", (q,)).fetchone()
    elif ph:
        user = conn.execute("SELECT id,name,city,phone FROM users WHERE phone=?", (ph,)).fetchone()
    else:
        conn.close()
        return jsonify({"error": "أدخل رقم الحساب أو الهاتف"}), 400
    conn.close()
    if not user or user["id"] == user_id:
        return jsonify({"error": "الحساب غير موجود"}), 404
    return jsonify({"id": user["id"], "name": user["name"], "city": user["city"]})

# ─────────────────────────────────────────────
# ROUTES — TRANSACTIONS
# ─────────────────────────────────────────────
@app.route("/api/transactions", methods=["GET"])
@auth_required
def get_transactions(user_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT t.id, t.from_user, t.to_user, t.amount, t.note, t.created_at,
               uf.name as from_name, ut.name as to_name
        FROM transactions t
        JOIN users uf ON uf.id = t.from_user
        JOIN users ut ON ut.id = t.to_user
        WHERE t.from_user=? OR t.to_user=?
        ORDER BY t.created_at DESC LIMIT 50
    """, (user_id, user_id)).fetchall()
    conn.close()

    txs = []
    for r in rows:
        if r["from_user"] == user_id:
            txs.append({"type":"send","name":r["to_name"],"amount":r["amount"],"date":fmt_date(r["created_at"]),"note":r["note"]})
        else:
            txs.append({"type":"receive","name":r["from_name"],"amount":r["amount"],"date":fmt_date(r["created_at"]),"note":r["note"]})
    return jsonify(txs)

@app.route("/api/transfer", methods=["POST"])
@auth_required
def transfer(user_id):
    data = request.json or {}
    to_id  = str(data.get("to","")).strip().upper()
    amount = float(data.get("amount", 0))
    note   = str(data.get("note","")).strip()
    pin    = str(data.get("pin","")).strip()

    if amount < 100:
        return jsonify({"error": "الحد الأدنى للتحويل 100 ل.س"}), 400

    conn = get_db()

    # Verify PIN
    sender = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not sender or sender["pin"] != hash_pw(pin):
        conn.close()
        return jsonify({"error": "رمز PIN غير صحيح"}), 403

    if sender["balance"] < amount:
        conn.close()
        return jsonify({"error": "الرصيد غير كافٍ"}), 400

    receiver = conn.execute("SELECT * FROM users WHERE id=?", (to_id,)).fetchone()
    if not receiver:
        conn.close()
        return jsonify({"error": "حساب المستلم غير موجود"}), 404

    if receiver["id"] == user_id:
        conn.close()
        return jsonify({"error": "لا يمكن التحويل لنفس الحساب"}), 400

    # Execute transfer atomically
    conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, user_id))
    conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, to_id))
    conn.execute(
        "INSERT INTO transactions (from_user,to_user,amount,note) VALUES (?,?,?,?)",
        (user_id, to_id, amount, note)
    )
    conn.commit()

    new_balance = conn.execute("SELECT balance FROM users WHERE id=?", (user_id,)).fetchone()["balance"]
    conn.close()

    return jsonify({
        "success": True,
        "message": f"تم تحويل {int(amount):,} ل.س إلى {receiver['name']} بنجاح",
        "new_balance": new_balance,
        "receiver_name": receiver["name"]
    })

# ─────────────────────────────────────────────
# ROUTES — ADMIN
# ─────────────────────────────────────────────
@app.route("/api/admin/users", methods=["GET"])
def admin_users():
    key = request.headers.get("X-Admin-Key","")
    if key != "goldmaster-admin-2026":
        return jsonify({"error": "غير مصرح"}), 403
    conn = get_db()
    users = conn.execute("SELECT id,name,phone,balance,city,status,created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])

@app.route("/api/admin/create-user", methods=["POST"])
def admin_create():
    key = request.headers.get("X-Admin-Key","")
    if key != "goldmaster-admin-2026":
        return jsonify({"error": "غير مصرح"}), 403
    data = request.json or {}
    uid  = generate_user_id()
    pw   = str(data.get("password","1234"))
    pin  = str(data.get("pin","1234"))
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (id,name,phone,password,pin,balance,city) VALUES (?,?,?,?,?,?,?)",
            (uid, data["name"], data["phone"], hash_pw(pw), hash_pw(pin), float(data.get("balance",0)), data.get("city",""))
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True, "id": uid})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 400

# ─────────────────────────────────────────────
# ROUTES — CHANGE PASSWORD / PIN
# ─────────────────────────────────────────────
@app.route("/api/change-password", methods=["POST"])
@auth_required
def change_password(user_id):
    data = request.json or {}
    old_pw = str(data.get("old_password",""))
    new_pw = str(data.get("new_password",""))
    if not old_pw or not new_pw:
        return jsonify({"error": "أدخل كلمة المرور الحالية والجديدة"}), 400
    if len(new_pw) < 4:
        return jsonify({"error": "كلمة المرور قصيرة جداً"}), 400
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user["password"] != hash_pw(old_pw):
        conn.close()
        return jsonify({"error": "كلمة المرور الحالية غير صحيحة"}), 403
    conn.execute("UPDATE users SET password=? WHERE id=?", (hash_pw(new_pw), user_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/change-pin", methods=["POST"])
@auth_required
def change_pin(user_id):
    data = request.json or {}
    old_pin = str(data.get("old_pin",""))
    new_pin = str(data.get("new_pin",""))
    if not old_pin or not new_pin:
        return jsonify({"error": "أدخل PIN الحالي والجديد"}), 400
    if len(new_pin) != 4 or not new_pin.isdigit():
        return jsonify({"error": "PIN يجب أن يكون 4 أرقام"}), 400
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user or user["pin"] != hash_pw(old_pin):
        conn.close()
        return jsonify({"error": "رمز PIN الحالي غير صحيح"}), 403
    conn.execute("UPDATE users SET pin=? WHERE id=?", (hash_pw(new_pin), user_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ─────────────────────────────────────────────
# ROUTES — ADMIN EXTENDED
# ─────────────────────────────────────────────
def admin_check():
    key = request.headers.get("X-Admin-Key","")
    return key == "goldmaster-admin-2026"

@app.route("/api/admin/all-transactions", methods=["GET"])
def admin_all_transactions():
    if not admin_check():
        return jsonify({"error": "غير مصرح"}), 403
    conn = get_db()
    rows = conn.execute("""
        SELECT t.id, t.from_user, t.to_user, t.amount, t.note, t.type, t.created_at,
               uf.name as from_name, ut.name as to_name
        FROM transactions t
        LEFT JOIN users uf ON uf.id = t.from_user
        LEFT JOIN users ut ON ut.id = t.to_user
        ORDER BY t.created_at DESC LIMIT 500
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/admin/find-user", methods=["GET"])
def admin_find_user():
    if not admin_check():
        return jsonify({"error": "غير مصرح"}), 403
    q = request.args.get("q","").strip().upper()
    conn = get_db()
    user = conn.execute(
        "SELECT id,name,phone,balance,city,status FROM users WHERE id=? OR phone=?",
        (q, request.args.get("q","").strip())
    ).fetchone()
    conn.close()
    if not user:
        return jsonify({"error": "الحساب غير موجود"}), 404
    return jsonify(dict(user))

@app.route("/api/admin/update-user/<uid>", methods=["POST"])
def admin_update_user(uid):
    if not admin_check():
        return jsonify({"error": "غير مصرح"}), 403
    data = request.json or {}
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "الحساب غير موجود"}), 404
    name   = data.get("name", user["name"])
    phone  = data.get("phone", user["phone"])
    city   = data.get("city", user["city"])
    status = data.get("status", user["status"])
    pw_hash = hash_pw(data["password"]) if data.get("password") else user["password"]
    try:
        conn.execute(
            "UPDATE users SET name=?,phone=?,city=?,status=?,password=? WHERE id=?",
            (name, phone, city, status, pw_hash, uid)
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 400

@app.route("/api/admin/deposit", methods=["POST"])
def admin_deposit():
    if not admin_check():
        return jsonify({"error": "غير مصرح"}), 403
    data    = request.json or {}
    uid     = str(data.get("user_id","")).strip().upper()
    amount  = float(data.get("amount", 0))
    op_type = str(data.get("type","deposit"))
    note    = str(data.get("note",""))
    if amount <= 0:
        return jsonify({"error": "أدخل مبلغاً صحيحاً"}), 400
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        conn.close()
        return jsonify({"error": "الحساب غير موجود"}), 404
    if op_type == "withdraw" and user["balance"] < amount:
        conn.close()
        return jsonify({"error": "رصيد العميل غير كافٍ للسحب"}), 400
    if op_type == "deposit":
        conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, uid))
    else:
        conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, uid))
    # Record with type field
    conn.execute(
        "INSERT INTO transactions (from_user,to_user,amount,note,type) VALUES (?,?,?,?,?)",
        (uid, uid, amount, note or ('إيداع يدوي' if op_type=='deposit' else 'سحب يدوي'), op_type)
    )
    conn.commit()
    new_bal = conn.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"]
    conn.close()
    return jsonify({"success": True, "new_balance": new_bal})

# ─────────────────────────────────────────────
# STATIC FILES
# ─────────────────────────────────────────────
@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/")
def index():
    base = os.path.dirname(__file__)
    # Try public/ first, then root
    for p in [os.path.join(base,"public","index.html"), os.path.join(base,"index.html")]:
        if os.path.exists(p):
            return send_file(p)
    return "index.html not found", 404

@app.route("/admin")
@app.route("/admin.html")
def admin_page():
    base = os.path.dirname(__file__)
    for p in [os.path.join(base,"public","admin.html"), os.path.join(base,"admin.html")]:
        if os.path.exists(p):
            return send_file(p)
    return "admin.html not found", 404

@app.route("/<path:path>")
def static_files(path):
    base = os.path.dirname(__file__)
    for folder in [os.path.join(base,"public"), base]:
        full = os.path.join(folder, path)
        if os.path.exists(full):
            return send_from_directory(folder, path)
    return "Not found", 404

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"🏅 غولد ماستر شغال على port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

# Called by gunicorn on Railway
init_db()
