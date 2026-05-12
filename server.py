#!/usr/bin/env python3
# غولد ماستر v3.0 - Gold Master Financial Server
# HTML fully embedded - no external files needed

import os, hashlib, secrets, sqlite3, time, base64
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

DB_PATH    = os.environ.get('DB_PATH', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'goldmaster.db'))
SECRET_KEY = os.environ.get('SECRET_KEY', 'goldmaster-haleb-2026')
ADMIN_KEY  = 'goldmaster-admin-2026'

# ─── DB ───
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def hp(pw):
    return hashlib.sha256((pw + SECRET_KEY).encode()).hexdigest()

def mktok(uid):
    exp = int(time.time()) + 86400
    sig = hashlib.sha256(f"{uid}:{exp}{SECRET_KEY}".encode()).hexdigest()[:16]
    return f"{uid}:{exp}:{sig}"

def vftok(tok):
    try:
        uid, exp, sig = tok.split(":")
        if int(exp) < int(time.time()): return None
        if hashlib.sha256(f"{uid}:{exp}{SECRET_KEY}".encode()).hexdigest()[:16] != sig: return None
        return uid
    except: return None

def init_db():
    con = db(); c = con.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL, pin TEXT NOT NULL, balance REAL DEFAULT 0,
        currency TEXT DEFAULT 'ل.س', city TEXT DEFAULT '', status TEXT DEFAULT 'نشط',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT, from_user TEXT, to_user TEXT,
        amount REAL, note TEXT DEFAULT '', type TEXT DEFAULT 'transfer',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    try: c.execute("ALTER TABLE transactions ADD COLUMN type TEXT DEFAULT 'transfer'")
    except: pass
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        for u in [("GM001234","أحمد محمد الحلبي","0911234567",hp("1234"),hp("1234"),250000,"حلب - الباب"),
                  ("GM005678","سارة أحمد الزعبي","0922345678",hp("5678"),hp("5678"),180000,"حلب"),
                  ("GM009999","محمد سعيد الرفاعي","0933456789",hp("9999"),hp("9999"),500000,"الباب")]:
            c.execute("INSERT OR IGNORE INTO users(id,name,phone,password,pin,balance,city) VALUES(?,?,?,?,?,?,?)", u)
        for t in [("GM005678","GM001234",50000,"دفعة شهرية","transfer"),
                  ("GM001234","GM005678",25000,"تحويل","transfer"),
                  ("GM009999","GM001234",120000,"راتب","transfer"),
                  ("GM001234","GM009999",15000,"فاتورة","transfer")]:
            c.execute("INSERT INTO transactions(from_user,to_user,amount,note,type) VALUES(?,?,?,?,?)", t)
    con.commit(); con.close()
    print("✅ DB ready")

def newid():
    con = db()
    while True:
        uid = "GM" + str(secrets.randbelow(900000)+100000)
        if not con.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone():
            con.close(); return uid

def fmtdate(s):
    try: return s[:16].replace('T',' ')
    except: return s or ''

def auth(f):
    from functools import wraps
    @wraps(f)
    def w(*a, **kw):
        tok = request.headers.get("Authorization","").replace("Bearer ","")
        uid = vftok(tok)
        if not uid: return jsonify({"error":"غير مصرح"}), 401
        return f(uid, *a, **kw)
    return w

def adm():
    return request.headers.get("X-Admin-Key","") == ADMIN_KEY

# ─── API ───
@app.route("/api/login", methods=["POST"])
def login():
    d = request.json or {}
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=? AND password=?",
                    (str(d.get("account","")).upper(), hp(str(d.get("password",""))))).fetchone()
    con.close()
    if not u: return jsonify({"error":"رقم الحساب أو كلمة المرور غير صحيحة"}), 401
    return jsonify({"token": mktok(u["id"]), "user": dict(u)})

@app.route("/api/me")
@auth
def me(uid):
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    con.close()
    return jsonify(dict(u)) if u else (jsonify({"error":"not found"}), 404)

@app.route("/api/lookup")
@auth
def lookup(uid):
    q = request.args.get("q","").upper()
    ph = request.args.get("phone","")
    con = db()
    u = con.execute("SELECT id,name,city,phone FROM users WHERE id=? OR phone=?", (q, ph)).fetchone()
    con.close()
    if not u or u["id"] == uid: return jsonify({"error":"الحساب غير موجود"}), 404
    return jsonify(dict(u))

@app.route("/api/transactions")
@auth
def txs(uid):
    con = db()
    rows = con.execute("""SELECT t.*,uf.name as from_name,ut.name as to_name FROM transactions t
        LEFT JOIN users uf ON uf.id=t.from_user LEFT JOIN users ut ON ut.id=t.to_user
        WHERE t.from_user=? OR t.to_user=? ORDER BY t.created_at DESC LIMIT 50""", (uid,uid)).fetchall()
    con.close()
    out = []
    for r in rows:
        t = dict(r)
        t["type"] = "send" if r["from_user"]==uid else "receive"
        t["name"] = r["to_name"] if r["from_user"]==uid else r["from_name"]
        t["date"] = fmtdate(r["created_at"])
        out.append(t)
    return jsonify(out)

@app.route("/api/transfer", methods=["POST"])
@auth
def transfer(uid):
    d = request.json or {}
    amt = float(d.get("amount",0))
    to  = str(d.get("to","")).upper()
    pin = str(d.get("pin",""))
    note = str(d.get("note",""))
    if amt < 100: return jsonify({"error":"الحد الأدنى 100 ل.س"}), 400
    con = db()
    s = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not s or s["pin"] != hp(pin): con.close(); return jsonify({"error":"رمز PIN غير صحيح"}), 403
    if s["balance"] < amt: con.close(); return jsonify({"error":"الرصيد غير كافٍ"}), 400
    r = con.execute("SELECT * FROM users WHERE id=?", (to,)).fetchone()
    if not r or r["id"]==uid: con.close(); return jsonify({"error":"حساب المستلم غير موجود"}), 404
    con.execute("UPDATE users SET balance=balance-? WHERE id=?", (amt,uid))
    con.execute("UPDATE users SET balance=balance+? WHERE id=?", (amt,to))
    con.execute("INSERT INTO transactions(from_user,to_user,amount,note,type) VALUES(?,?,?,?,?)",(uid,to,amt,note,"transfer"))
    con.commit()
    nb = con.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"]
    con.close()
    return jsonify({"success":True,"new_balance":nb,"receiver_name":r["name"]})

@app.route("/api/change-password", methods=["POST"])
@auth
def chpw(uid):
    d = request.json or {}
    o,n = str(d.get("old_password","")), str(d.get("new_password",""))
    if len(n)<4: return jsonify({"error":"كلمة المرور قصيرة"}), 400
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["password"]!=hp(o): con.close(); return jsonify({"error":"كلمة المرور الحالية غير صحيحة"}), 403
    con.execute("UPDATE users SET password=? WHERE id=?", (hp(n),uid)); con.commit(); con.close()
    return jsonify({"success":True})

@app.route("/api/change-pin", methods=["POST"])
@auth
def chpin(uid):
    d = request.json or {}
    o,n = str(d.get("old_pin","")), str(d.get("new_pin",""))
    if len(n)!=4 or not n.isdigit(): return jsonify({"error":"PIN يجب 4 أرقام"}), 400
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["pin"]!=hp(o): con.close(); return jsonify({"error":"PIN الحالي غير صحيح"}), 403
    con.execute("UPDATE users SET pin=? WHERE id=?", (hp(n),uid)); con.commit(); con.close()
    return jsonify({"success":True})

@app.route("/api/admin/users")
def au():
    if not adm(): return jsonify({"error":"غير مصرح"}), 403
    con = db()
    u = con.execute("SELECT id,name,phone,balance,city,status,created_at FROM users ORDER BY created_at DESC").fetchall()
    con.close(); return jsonify([dict(x) for x in u])

@app.route("/api/admin/create-user", methods=["POST"])
def acu():
    if not adm(): return jsonify({"error":"غير مصرح"}), 403
    d = request.json or {}
    uid = newid(); con = db()
    try:
        con.execute("INSERT INTO users(id,name,phone,password,pin,balance,city) VALUES(?,?,?,?,?,?,?)",
                    (uid,d["name"],d["phone"],hp(d.get("password","1234")),hp(d.get("pin","1234")),float(d.get("balance",0)),d.get("city","")))
        con.commit(); con.close(); return jsonify({"success":True,"id":uid})
    except Exception as e: con.close(); return jsonify({"error":str(e)}), 400

@app.route("/api/admin/all-transactions")
def aat():
    if not adm(): return jsonify({"error":"غير مصرح"}), 403
    con = db()
    rows = con.execute("""SELECT t.*,uf.name as from_name,ut.name as to_name FROM transactions t
        LEFT JOIN users uf ON uf.id=t.from_user LEFT JOIN users ut ON ut.id=t.to_user
        ORDER BY t.created_at DESC LIMIT 500""").fetchall()
    con.close(); return jsonify([dict(r) for r in rows])

@app.route("/api/admin/find-user")
def afu():
    if not adm(): return jsonify({"error":"غير مصرح"}), 403
    q = request.args.get("q","").strip()
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=? OR phone=?", (q.upper(), q)).fetchone()
    con.close()
    return jsonify(dict(u)) if u else (jsonify({"error":"غير موجود"}), 404)

@app.route("/api/admin/update-user/<uid>", methods=["POST"])
def auu(uid):
    if not adm(): return jsonify({"error":"غير مصرح"}), 403
    d = request.json or {}; con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u: con.close(); return jsonify({"error":"غير موجود"}), 404
    pw = hp(d["password"]) if d.get("password") else u["password"]
    try:
        con.execute("UPDATE users SET name=?,phone=?,city=?,status=?,password=? WHERE id=?",
                    (d.get("name",u["name"]),d.get("phone",u["phone"]),d.get("city",u["city"]),d.get("status",u["status"]),pw,uid))
        con.commit(); con.close(); return jsonify({"success":True})
    except Exception as e: con.close(); return jsonify({"error":str(e)}), 400

@app.route("/api/admin/deposit", methods=["POST"])
def adep():
    if not adm(): return jsonify({"error":"غير مصرح"}), 403
    d = request.json or {}
    uid = str(d.get("user_id","")).upper()
    amt = float(d.get("amount",0))
    tp  = str(d.get("type","deposit"))
    note = str(d.get("note",""))
    if amt <= 0: return jsonify({"error":"مبلغ غير صحيح"}), 400
    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u: con.close(); return jsonify({"error":"غير موجود"}), 404
    if tp=="withdraw" and u["balance"]<amt: con.close(); return jsonify({"error":"رصيد غير كافٍ"}), 400
    op = amt if tp=="deposit" else -amt
    con.execute("UPDATE users SET balance=balance+? WHERE id=?", (op,uid))
    con.execute("INSERT INTO transactions(from_user,to_user,amount,note,type) VALUES(?,?,?,?,?)",
                (uid,uid,amt,note or ("إيداع" if tp=="deposit" else "سحب"),tp))
    con.commit()
    nb = con.execute("SELECT balance FROM users WHERE id=?", (uid,)).fetchone()["balance"]
    con.close(); return jsonify({"success":True,"new_balance":nb})

# ─── PAGES ───
@app.after_request
def hdrs(r):
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    r.headers["Pragma"] = "no-cache"
    return r

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>غولد ماستر</title>
<style>
:root{--g:#D4A843;--g2:#F0C560;--g3:#8B6914;--gg:rgba(212,168,67,.22);--ink:#07070C;--i2:#0F0F18;--i3:#161622;--i4:#1C1C2A;--i5:#222234;--gl:rgba(255,255,255,.05);--gl2:rgba(255,255,255,.08);--b:rgba(255,255,255,.08);--b2:rgba(255,255,255,.13);--tx:#EDE9E0;--tx2:#9E9894;--tx3:#4A4848;--ok:#00C896;--ok2:rgba(0,200,150,.12);--er:#FF4757;--er2:rgba(255,71,87,.12);--bl:#4A8FE2;--r:14px;--rl:20px;--rx:26px;--f:'Noto Kufi Arabic',system-ui,sans-serif}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden;font-family:var(--f)}
body{background:var(--ink);color:var(--tx);display:flex;justify-content:center}
body::before{content:'';position:fixed;inset:0;pointer-events:none;background:radial-gradient(ellipse 120% 60% at 110% -10%,rgba(212,168,67,.08),transparent 55%),radial-gradient(ellipse 80% 50% at -20% 110%,rgba(74,143,226,.05),transparent 55%)}
#app{position:relative;z-index:1;width:100%;max-width:430px;height:100%;display:flex;flex-direction:column;overflow:hidden}
.v{display:none;flex-direction:column;flex:1;overflow:hidden}.v.on{display:flex;animation:vi .35s cubic-bezier(.16,1,.3,1) both}
@keyframes vi{from{opacity:0;transform:translateY(18px)}to{opacity:1;transform:translateY(0)}}

/* LOGIN */
#vL{justify-content:flex-end;position:relative}
.lb-wrap{position:absolute;inset:0;overflow:hidden}
.orb{position:absolute;border-radius:50%;filter:blur(70px);pointer-events:none}
.o1{width:320px;height:320px;top:-80px;right:-80px;background:radial-gradient(circle,rgba(212,168,67,.3),transparent 70%);animation:o1 8s ease-in-out infinite alternate}
.o2{width:260px;height:260px;bottom:-60px;left:-60px;background:radial-gradient(circle,rgba(74,143,226,.18),transparent 70%);animation:o2 10s ease-in-out infinite alternate}
.o3{width:180px;height:180px;top:35%;right:25%;background:radial-gradient(circle,rgba(168,85,247,.12),transparent 70%);animation:o3 12s ease-in-out infinite alternate}
@keyframes o1{to{transform:translate(-20px,30px) scale(1.1)}}@keyframes o2{to{transform:translate(20px,-30px) scale(1.15)}}@keyframes o3{to{transform:translate(-30px,20px) scale(.9)}}
.lhero{position:relative;z-index:1;padding:60px 32px 0;display:flex;flex-direction:column;align-items:center;flex:1}
.logo-wrap{margin-bottom:28px;animation:li 1s cubic-bezier(.16,1,.3,1) both;position:relative}
@keyframes li{from{opacity:0;transform:scale(.5) rotate(-15deg)}to{opacity:1;transform:scale(1) rotate(0)}}
.logo-p1{position:absolute;inset:-16px;border-radius:42px;border:1px solid rgba(212,168,67,.12);animation:lp 3s ease-in-out infinite}
.logo-p2{position:absolute;inset:-8px;border-radius:34px;border:1px solid rgba(212,168,67,.2);animation:lp 3s ease-in-out infinite .5s}
@keyframes lp{0%,100%{opacity:.4;transform:scale(1)}50%{opacity:.9;transform:scale(1.04)}}
.logo-box{width:88px;height:88px;border-radius:26px;background:linear-gradient(145deg,var(--g3),var(--g),var(--g2));display:flex;align-items:center;justify-content:center;font-size:42px;box-shadow:0 0 0 1px rgba(212,168,67,.3),0 0 60px rgba(212,168,67,.2),0 16px 40px rgba(0,0,0,.5);position:relative;overflow:hidden}
.logo-box::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,transparent 45%,rgba(255,255,255,.12))}
.lname{font-size:30px;font-weight:900;background:linear-gradient(135deg,var(--g2),var(--g),var(--g3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-top:16px;letter-spacing:-.3px}
.lsub{font-size:11px;color:var(--tx3);letter-spacing:2px;margin-top:4px;font-weight:500;text-transform:uppercase}
.ltag{font-size:14px;color:var(--tx2);text-align:center;line-height:1.8;margin-top:18px}
.lcard{position:relative;z-index:1;background:var(--i2);border:1px solid var(--b2);border-radius:var(--rx) var(--rx) 0 0;padding:32px 28px max(32px,env(safe-area-inset-bottom));box-shadow:0 -20px 60px rgba(0,0,0,.4)}
.ltitle{font-size:22px;font-weight:800;margin-bottom:22px}.ltitle span{color:var(--g)}
.fw{margin-bottom:14px}
.fl{font-size:10px;color:var(--g);font-weight:700;letter-spacing:.8px;margin-bottom:7px;display:block;text-transform:uppercase}
.fi{width:100%;background:rgba(255,255,255,.04);border:1.5px solid var(--b);border-radius:var(--r);padding:15px 18px;color:var(--tx);font-size:15px;font-family:var(--f);outline:none;direction:ltr;text-align:right;transition:all .3s;letter-spacing:.5px}
.fi:focus{border-color:var(--g);background:var(--gl2);box-shadow:0 0 0 3px var(--gg)}
.fi::placeholder{color:var(--tx3)}
.bg{width:100%;background:linear-gradient(135deg,var(--g3),var(--g) 50%,var(--g2));border:none;border-radius:var(--r);padding:17px;color:#080808;font-size:16px;font-weight:800;font-family:var(--f);cursor:pointer;box-shadow:0 4px 24px var(--gg);transition:all .3s;margin-top:4px;position:relative;overflow:hidden}
.bg::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,transparent 40%,rgba(255,255,255,.1))}
.bg:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 8px 32px rgba(212,168,67,.35)}
.bg:active{transform:scale(.98)}.bg:disabled{opacity:.5;cursor:not-allowed;transform:none}
.em{display:none;background:var(--er2);border:1px solid rgba(255,71,87,.25);border-radius:10px;padding:12px;color:var(--er);font-size:13px;text-align:center;margin-top:10px;font-weight:600}

/* SHELL */
#vM{flex:1}
.tb{padding:14px 20px 10px;display:flex;align-items:center;justify-content:space-between;background:rgba(7,7,12,.96);backdrop-filter:blur(32px);border-bottom:1px solid var(--b);flex-shrink:0;position:relative}
.tb::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(212,168,67,.15),transparent)}
.tb-lo{display:flex;align-items:center;gap:10px}
.tb-ic{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--g3),var(--g));display:flex;align-items:center;justify-content:center;font-size:16px;box-shadow:0 4px 12px rgba(212,168,67,.28)}
.tb-nm{font-size:17px;font-weight:900;color:var(--g);letter-spacing:-.3px}
.tb-ri{display:flex;align-items:center;gap:10px}
.tb-us{font-size:12px;color:var(--tx3);font-weight:500}
.notif{width:34px;height:34px;background:var(--gl);border:1px solid var(--b);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:15px;cursor:pointer;position:relative}
.ndot{position:absolute;top:6px;right:6px;width:7px;height:7px;background:var(--er);border-radius:50%;border:1.5px solid var(--ink)}
.bout{background:rgba(255,71,87,.1);border:1px solid rgba(255,71,87,.2);color:var(--er);border-radius:8px;padding:6px 12px;font-size:11px;font-weight:700;font-family:var(--f);cursor:pointer;transition:all .2s}
.bout:hover{background:rgba(255,71,87,.2)}
.tw{flex:1;overflow:hidden}
.tp{display:none;height:100%;overflow-y:auto;padding:20px}.tp::-webkit-scrollbar{width:0}.tp.on{display:block;animation:vi .3s both}
.bn{display:flex;flex-shrink:0;background:rgba(7,7,12,.98);backdrop-filter:blur(32px);border-top:1px solid var(--b);padding:6px 0 max(18px,env(safe-area-inset-bottom))}
.bni{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px;cursor:pointer;border:none;background:transparent;color:var(--tx3);font-family:var(--f);transition:all .25s}
.bni-i{font-size:20px;transition:all .25s;width:40px;height:32px;border-radius:10px;display:flex;align-items:center;justify-content:center}
.bni-l{font-size:10px;font-weight:700;letter-spacing:.3px}
.bni.on{color:var(--g)}.bni.on .bni-i{background:rgba(212,168,67,.12);filter:drop-shadow(0 0 6px var(--g))}

/* CARDS */
.cg{background:linear-gradient(145deg,#0D0A00,#1A1200,#0D0A00);border:1px solid rgba(212,168,67,.2);border-radius:var(--rx);padding:26px 22px;margin-bottom:14px;position:relative;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,.4),0 0 60px rgba(212,168,67,.06)}
.cg-gl1{position:absolute;top:-60px;right:-60px;width:220px;height:220px;background:radial-gradient(circle,rgba(212,168,67,.15),transparent 70%);border-radius:50%}
.cg-gl2{position:absolute;bottom:-40px;left:-40px;width:160px;height:160px;background:radial-gradient(circle,rgba(74,143,226,.07),transparent 70%);border-radius:50%}
.cg-pat{position:absolute;inset:0;opacity:.025;background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.5) 0,rgba(255,255,255,.5) 1px,transparent 0,transparent 50%);background-size:20px 20px}
.cg-chip{position:absolute;bottom:14px;left:18px;font-size:50px;opacity:.07}
.cg-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
.cg-badge{display:inline-flex;align-items:center;gap:6px;background:rgba(0,200,150,.1);border:1px solid rgba(0,200,150,.2);border-radius:99px;padding:4px 12px;font-size:11px;color:var(--ok);font-weight:700;letter-spacing:.3px}
.cg-badge::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--ok)}
.cg-lbl{font-size:10px;color:rgba(212,168,67,.5);letter-spacing:1.5px;font-weight:600;margin-bottom:8px;text-transform:uppercase}
.cg-amt{font-size:40px;font-weight:900;line-height:1;background:linear-gradient(135deg,var(--g2),var(--g));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-1px}
.cg-cur{font-size:18px;margin-left:5px;opacity:.8}
.cg-bot{display:flex;align-items:flex-end;justify-content:space-between;margin-top:18px}
.cg-id{font-size:11px;color:rgba(212,168,67,.35);letter-spacing:1px;font-family:monospace}
.cg-info{font-size:11px;color:rgba(255,255,255,.18);text-align:left}
.sr{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.sb{background:var(--gl);border:1px solid var(--b);border-radius:var(--r);padding:14px;transition:all .25s}
.sb:hover{background:var(--gl2)}
.sb-ic{width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;margin-bottom:10px}
.sb-l{font-size:10px;color:var(--tx3);font-weight:600;margin-bottom:4px;letter-spacing:.3px}
.sb-v{font-size:17px;font-weight:800}.sb-v.er{color:var(--er)}.sb-v.ok{color:var(--ok)}
.qa{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px}
.qb{background:var(--gl);border:1px solid var(--b);border-radius:var(--rl);padding:18px 14px;display:flex;flex-direction:column;align-items:flex-start;gap:8px;cursor:pointer;transition:all .3s}
.qb:hover{border-color:var(--b2);transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.qb:active{transform:scale(.97)}
.qi{width:44px;height:44px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:20px}
.qb.s .qi{background:var(--er2)}.qb.r .qi{background:var(--ok2)}
.qn{font-size:13px;font-weight:800}.qs{font-size:11px;color:var(--tx3);font-weight:500}
.stt{font-size:14px;font-weight:800;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.stt::before{content:'';width:3px;height:16px;background:linear-gradient(to bottom,var(--g),var(--g3));border-radius:2px}
.tl{display:flex;flex-direction:column;gap:8px}
.tx{background:var(--gl);border:1px solid var(--b);border-radius:var(--r);padding:13px 15px;display:flex;align-items:center;gap:12px;transition:all .2s}
.tx:hover{border-color:var(--b2);background:var(--gl2)}
.ti{width:40px;height:40px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;font-weight:700}
.ti.s{background:var(--er2);color:var(--er)}.ti.r{background:var(--ok2);color:var(--ok)}
.td{flex:1;min-width:0}.tn{font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tm{font-size:11px;color:var(--tx3);margin-top:2px;font-weight:500}
.ta{font-size:14px;font-weight:900;white-space:nowrap}.ta.s{color:var(--er)}.ta.r{color:var(--ok)}
.pg-h{font-size:22px;font-weight:900;letter-spacing:-.5px;margin-bottom:4px}.pg-h span{color:var(--g)}
.pg-s{font-size:12px;color:var(--tx3);margin-bottom:18px;font-weight:500}
.fc{background:var(--gl);border:1px solid var(--b);border-radius:var(--rl);padding:20px;margin-bottom:14px}
.fc-t{font-size:14px;font-weight:800;color:var(--g);margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--b);display:flex;align-items:center;gap:8px}
.fg{margin-bottom:13px}
.flab{font-size:10px;color:var(--g);font-weight:700;letter-spacing:.8px;margin-bottom:7px;display:block;text-transform:uppercase}
.fin{width:100%;background:var(--i3);border:1.5px solid var(--b);border-radius:var(--r);padding:13px 15px;color:var(--tx);font-size:14px;font-family:var(--f);outline:none;transition:all .3s}
.fin:focus{border-color:var(--g);background:var(--i4);box-shadow:0 0 0 3px var(--gg)}
.fin::placeholder{color:var(--tx3)}
.fin.ltr{direction:ltr;text-align:left}
select.fin{appearance:none;cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23D4A843'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:left 14px center;padding-left:36px}
.rf{background:rgba(0,200,150,.06);border:1px solid rgba(0,200,150,.2);border-radius:var(--r);padding:13px;margin-bottom:13px;display:none;align-items:center;gap:12px}.rf.on{display:flex}
.rav{width:38px;height:38px;border-radius:11px;background:linear-gradient(135deg,var(--g3),var(--g));display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0}
.rnm{font-size:14px;font-weight:700}.rid{font-size:11px;color:var(--ok);margin-top:2px;font-weight:600}
.rck{margin-right:auto;color:var(--ok);font-size:20px}
.rnf{background:var(--er2);border:1px solid rgba(255,71,87,.22);border-radius:var(--r);padding:11px;margin-bottom:13px;color:var(--er);font-size:13px;text-align:center;display:none;font-weight:600}.rnf.on{display:block}
.ap{background:linear-gradient(135deg,rgba(212,168,67,.07),rgba(212,168,67,.02));border:1px solid rgba(212,168,67,.15);border-radius:var(--r);padding:14px;text-align:center;margin-bottom:13px;display:none}.ap.on{display:block}
.apl{font-size:10px;color:var(--tx3);margin-bottom:3px;font-weight:600;letter-spacing:.8px;text-transform:uppercase}
.apv{font-size:28px;font-weight:900;color:var(--g);letter-spacing:-1px}
.ba{width:100%;background:linear-gradient(135deg,var(--g3),var(--g) 50%,var(--g2));border:none;border-radius:var(--r);padding:16px;color:#080808;font-size:15px;font-weight:800;font-family:var(--f);cursor:pointer;box-shadow:0 4px 20px var(--gg);transition:all .3s;position:relative;overflow:hidden}
.ba::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,transparent 40%,rgba(255,255,255,.1))}
.ba:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 8px 28px rgba(212,168,67,.3)}
.ba:active{transform:scale(.98)}.ba:disabled{opacity:.5;cursor:not-allowed;transform:none}
.bo{width:100%;background:transparent;border:1.5px solid var(--b2);border-radius:var(--r);padding:14px;color:var(--tx2);font-size:14px;font-weight:700;font-family:var(--f);cursor:pointer;transition:all .25s;margin-top:8px}
.bo:hover{background:var(--gl2)}.bo.rd{border-color:rgba(255,71,87,.28);color:var(--er)}.bo.rd:hover{background:var(--er2)}
.ab2{display:inline-block;background:linear-gradient(135deg,rgba(212,168,67,.1),rgba(212,168,67,.03));border:1.5px solid rgba(212,168,67,.28);border-radius:var(--r);padding:18px 28px;margin-bottom:16px}
.an{font-size:22px;font-weight:900;letter-spacing:3px;background:linear-gradient(135deg,var(--g2),var(--g));-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-family:monospace}
.cpb{background:rgba(212,168,67,.1);border:1px solid rgba(212,168,67,.22);border-radius:9px;padding:9px 18px;color:var(--g);font-size:12px;font-weight:700;font-family:var(--f);cursor:pointer;transition:all .2s;display:inline-flex;align-items:center;gap:6px;margin-bottom:16px}
.cpb:hover{background:rgba(212,168,67,.2)}
.ph2{background:var(--gl);border:1px solid var(--b);border-radius:var(--rl);padding:22px 18px;display:flex;align-items:center;gap:14px;margin-bottom:14px}
.pav{width:58px;height:58px;border-radius:16px;background:linear-gradient(135deg,var(--g3),var(--g));display:flex;align-items:center;justify-content:center;font-size:26px;box-shadow:0 4px 16px var(--gg);flex-shrink:0}
.pnm{font-size:18px;font-weight:800;letter-spacing:-.3px}.pid{font-size:11px;color:var(--tx3);margin-top:3px;font-family:monospace;letter-spacing:1px}
.pst{display:inline-flex;align-items:center;gap:5px;background:var(--ok2);border:1px solid rgba(0,200,150,.18);border-radius:99px;padding:3px 9px;margin-top:6px;font-size:10px;color:var(--ok);font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.pst::before{content:'';width:5px;height:5px;border-radius:50%;background:var(--ok)}
.ic{background:var(--gl);border:1px solid var(--b);border-radius:var(--r);overflow:hidden;margin-bottom:12px}
.ir{display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:1px solid var(--b);transition:background .15s}
.ir:last-child{border-bottom:none}.ir:hover{background:var(--gl2)}
.irl{font-size:12px;color:var(--tx3);display:flex;align-items:center;gap:7px;font-weight:600}
.irv{font-size:12px;font-weight:700}
.sc{background:var(--gl);border:1px solid var(--b);border-radius:var(--rl);padding:18px;margin-bottom:12px}
.sct{font-size:13px;font-weight:800;color:var(--g);margin-bottom:14px;padding-bottom:11px;border-bottom:1px solid var(--b);display:flex;align-items:center;gap:8px}

/* MODALS */
.ov{position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.88);backdrop-filter:blur(16px);display:flex;align-items:flex-end;justify-content:center;opacity:0;pointer-events:none;transition:opacity .3s}
.ov.on{opacity:1;pointer-events:all}
.ms{background:var(--i2);border:1px solid var(--b2);border-radius:var(--rx) var(--rx) 0 0;padding:30px 22px max(36px,env(safe-area-inset-bottom));width:100%;max-width:430px;text-align:center;transform:translateY(100%);transition:transform .45s cubic-bezier(.16,1,.3,1)}
.ov.on .ms{transform:translateY(0)}
.ms-drag{width:36px;height:4px;background:var(--b2);border-radius:2px;margin:0 auto 22px}
.m-ic{font-size:52px;margin-bottom:12px}.m-ti{font-size:21px;font-weight:900;margin-bottom:5px;letter-spacing:-.3px}
.m-su{font-size:13px;color:var(--tx3);line-height:1.7;margin-bottom:4px;font-weight:500}
.m-am{font-size:34px;font-weight:900;color:var(--g);margin:12px 0 20px;letter-spacing:-1px}
.pds{display:flex;justify-content:center;gap:12px;margin-bottom:22px}
.pd{width:14px;height:14px;border-radius:50%;border:2px solid rgba(212,168,67,.3);background:transparent;transition:all .2s}
.pd.on{background:var(--g);border-color:var(--g);transform:scale(1.15);box-shadow:0 0 12px rgba(212,168,67,.4)}
.kp{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:13px}
.kb{background:var(--gl);border:1px solid var(--b);border-radius:var(--r);padding:17px;color:var(--tx);font-size:22px;font-weight:700;font-family:var(--f);cursor:pointer;transition:all .15s;display:flex;align-items:center;justify-content:center}
.kb:hover{background:var(--gl2);border-color:var(--b2)}.kb:active{transform:scale(.92)}
.kb.dl{font-size:17px;color:var(--er)}.kb.cf{background:linear-gradient(135deg,var(--g3),var(--g));color:#080808;border:none;font-size:20px;font-weight:900}
#toast{position:fixed;top:18px;left:50%;transform:translateX(-50%) translateY(-110px);background:var(--i3);border-radius:var(--r);padding:12px 18px;font-size:13px;font-weight:700;z-index:200;transition:transform .4s cubic-bezier(.16,1,.3,1);border:1px solid var(--b2);box-shadow:0 8px 32px rgba(0,0,0,.5);white-space:nowrap;pointer-events:none}
#toast.on{transform:translateX(-50%) translateY(0)}
#toast.ok{border-color:rgba(0,200,150,.35);color:var(--ok)}
#toast.er{border-color:rgba(255,71,87,.35);color:var(--er)}
#toast.in{border-color:rgba(212,168,67,.35);color:var(--g)}
.sp{display:inline-block;width:15px;height:15px;border:2px solid rgba(255,255,255,.15);border-top-color:var(--g);border-radius:50%;animation:spn .7s linear infinite;vertical-align:middle;margin-left:8px}
@keyframes spn{to{transform:rotate(360deg)}}
.emp{text-align:center;padding:36px;color:var(--tx3)}.emp-i{font-size:42px;margin-bottom:10px;opacity:.3}.emp-t{font-size:13px;font-weight:600}
@media(min-width:430px){body{background:#040408}#app{box-shadow:0 0 120px rgba(0,0,0,.9)}}
</style>
</head>
<body>
<div id="app">
<div class="v on" id="vL">
  <div class="lb-wrap"><div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div></div>
  <div class="lhero">
    <div class="logo-wrap">
      <div class="logo-p1"></div><div class="logo-p2"></div>
      <div class="logo-box">🏅</div>
    </div>
    <div class="lname">غولد ماستر</div>
    <div class="lsub">Gold Master · Financial Services</div>
    <div class="ltag">خدمات مالية موثوقة وآمنة<br>في متناول يدك</div>
  </div>
  <div class="lcard">
    <div class="ltitle">مرحباً بك <span>👋</span></div>
    <div class="fw"><label class="fl">رقم الحساب</label><input class="fi ltr" id="la" type="text" placeholder="GM000000" maxlength="10"></div>
    <div class="fw"><label class="fl">كلمة المرور</label><input class="fi ltr" id="lp" type="password" placeholder="••••••••"></div>
    <button class="bg" id="lb" onclick="doLogin()">الدخول إلى حسابي</button>
    <div class="em" id="le"></div>
  </div>
</div>

<div class="v" id="vM">
  <div class="tb">
    <div class="tb-lo"><div class="tb-ic">🏅</div><span class="tb-nm">غولد ماستر</span></div>
    <div class="tb-ri">
      <span class="tb-us" id="tbu"></span>
      <div class="notif">🔔<div class="ndot"></div></div>
      <button class="bout" onclick="doLogout()">خروج</button>
    </div>
  </div>
  <div class="tw">
    <div class="tp on" id="tph"></div>
    <div class="tp" id="tps"></div>
    <div class="tp" id="tpr"></div>
    <div class="tp" id="tpp"></div>
  </div>
  <div class="bn">
    <button class="bni on" onclick="gT('h',this)"><div class="bni-i">🏠</div><span class="bni-l">الرئيسية</span></button>
    <button class="bni" onclick="gT('s',this)"><div class="bni-i">📤</div><span class="bni-l">تحويل</span></button>
    <button class="bni" onclick="gT('r',this)"><div class="bni-i">📥</div><span class="bni-l">استلام</span></button>
    <button class="bni" onclick="gT('p',this)"><div class="bni-i">👤</div><span class="bni-l">حسابي</span></button>
  </div>
</div>
</div>

<div class="ov" id="mPin">
  <div class="ms">
    <div class="ms-drag"></div>
    <div class="m-ic">🔐</div><div class="m-ti">تأكيد التحويل</div>
    <div class="m-su" id="pSb"></div><div class="m-am" id="pAm"></div>
    <div class="pds"><div class="pd" id="pd1"></div><div class="pd" id="pd2"></div><div class="pd" id="pd3"></div><div class="pd" id="pd4"></div></div>
    <div class="kp">
      <button class="kb" onclick="pk('1')">١</button><button class="kb" onclick="pk('2')">٢</button><button class="kb" onclick="pk('3')">٣</button>
      <button class="kb" onclick="pk('4')">٤</button><button class="kb" onclick="pk('5')">٥</button><button class="kb" onclick="pk('6')">٦</button>
      <button class="kb" onclick="pk('7')">٧</button><button class="kb" onclick="pk('8')">٨</button><button class="kb" onclick="pk('9')">٩</button>
      <button class="kb dl" onclick="pdl()">⌫</button><button class="kb" onclick="pk('0')">٠</button><button class="kb cf" onclick="pcf()">✓</button>
    </div>
    <button class="bo" onclick="clPin()">إلغاء</button>
  </div>
</div>

<div class="ov" id="mSuc">
  <div class="ms">
    <div class="ms-drag"></div>
    <div class="m-ic">✅</div><div class="m-ti" style="color:var(--ok)">تمت العملية بنجاح!</div>
    <div class="m-am" id="sAm"></div><div class="m-su" id="sSb" style="white-space:pre-line"></div>
    <button class="ba" onclick="clSuc()" style="margin-top:18px">رائع 🎉</button>
  </div>
</div>
<div id="toast"></div>

<script>
const A='';let tok=localStorage.getItem('gt'),me=JSON.parse(localStorage.getItem('gm')||'null'),pinB='',pTx=null,tT;
async function api(m,p,b){const o={method:m,headers:{'Content-Type':'application/json'}};if(tok)o.headers['Authorization']='Bearer '+tok;if(b)o.body=JSON.stringify(b);const r=await fetch(A+p,o),d=await r.json();if(!r.ok)throw new Error(d.error||'خطأ');return d}
async function doLogin(){const a=document.getElementById('la').value.trim().toUpperCase(),p=document.getElementById('lp').value,btn=document.getElementById('lb'),e=document.getElementById('le');if(!a||!p){sE('أدخل رقم الحساب وكلمة المرور');return}btn.disabled=true;btn.innerHTML='جاري الدخول <span class="sp"></span>';e.style.display='none';try{const d=await api('POST','/api/login',{account:a,password:p});tok=d.token;me=d.user;localStorage.setItem('gt',tok);localStorage.setItem('gm',JSON.stringify(me));document.getElementById('tbu').textContent=me.name.split(' ')[0];sV('vM');gT('h',document.querySelector('.bni'))}catch(x){sE(x.message)}finally{btn.disabled=false;btn.innerHTML='الدخول إلى حسابي'}}
function sE(m){const e=document.getElementById('le');e.textContent='⚠ '+m;e.style.display='block'}
function doLogout(){tok=null;me=null;localStorage.removeItem('gt');localStorage.removeItem('gm');document.getElementById('la').value='';document.getElementById('lp').value='';sV('vL')}
function sV(id){document.querySelectorAll('.v').forEach(v=>v.classList.remove('on'));document.getElementById(id).classList.add('on')}
function gT(t,el){document.querySelectorAll('.bni').forEach(b=>b.classList.remove('on'));el.classList.add('on');document.querySelectorAll('.tp').forEach(p=>p.classList.remove('on'));document.getElementById('tp'+t).classList.add('on');if(t==='h')rH();else if(t==='s')rS();else if(t==='r')rR();else if(t==='p')rP()}
function nTo(t){const m={h:0,s:1,r:2,p:3};gT(t,document.querySelectorAll('.bni')[m[t]])}
async function rH(){const p=document.getElementById('tph'),hr=new Date().getHours(),g=hr<12?'صباح الخير':hr<17?'مساء الخير':'مساء النور';p.innerHTML=`<div class="pg-h">${g}، <span>${me.name.split(' ')[0]}</span> 👋</div><div class="pg-s">إليك ملخص حسابك</div><div class="cg"><div class="cg-gl1"></div><div class="cg-gl2"></div><div class="cg-pat"></div><div class="cg-chip">💎</div><div class="cg-top"><div class="cg-badge">نشط</div><span style="font-size:18px;opacity:.3">•••</span></div><div class="cg-lbl">الرصيد المتاح</div><div class="cg-amt" id="bAmt"><span class="cg-cur">${me.currency}</span> ${me.balance.toLocaleString('ar')}</div><div class="cg-bot"><div class="cg-id">${me.id}</div><div class="cg-info">${me.city}<br>${me.phone}</div></div></div><div class="sr"><div class="sb"><div class="sb-ic" style="background:var(--er2)">📤</div><div class="sb-l">إجمالي المرسل</div><div class="sb-v er" id="stO">—</div></div><div class="sb"><div class="sb-ic" style="background:var(--ok2)">📥</div><div class="sb-l">إجمالي المستلم</div><div class="sb-v ok" id="stI">—</div></div></div><div class="qa"><div class="qb s" onclick="nTo('s')"><div class="qi">↗</div><div class="qn">تحويل</div><div class="qs">أرسل للآخرين</div></div><div class="qb r" onclick="nTo('r')"><div class="qi">↙</div><div class="qn">استلام</div><div class="qs">شارك رقمك</div></div></div><div class="stt">آخر المعاملات</div><div class="tl" id="txL"><div class="emp"><div class="emp-i">⏳</div><div class="emp-t">جاري التحميل...</div></div></div>`;
try{const[fr,txs]=await Promise.all([api('GET','/api/me'),api('GET','/api/transactions')]);me.balance=fr.balance;localStorage.setItem('gm',JSON.stringify(me));document.getElementById('bAmt').innerHTML=`<span class="cg-cur">${me.currency}</span> ${me.balance.toLocaleString('ar')}`;let o=0,i=0;txs.forEach(t=>{if(t.type==='send')o+=t.amount;else i+=t.amount});document.getElementById('stO').textContent=o.toLocaleString('ar')+' '+me.currency;document.getElementById('stI').textContent=i.toLocaleString('ar')+' '+me.currency;const l=document.getElementById('txL');if(!txs.length){l.innerHTML='<div class="emp"><div class="emp-i">📋</div><div class="emp-t">لا توجد معاملات بعد</div></div>';return}l.innerHTML=txs.map(t=>`<div class="tx"><div class="ti ${t.type==='send'?'s':'r'}">${t.type==='send'?'↗':'↙'}</div><div class="td"><div class="tn">${t.name}</div><div class="tm">${t.date}${t.note?' · '+t.note:''}</div></div><div class="ta ${t.type==='send'?'s':'r'}">${t.type==='send'?'−':'+'}${t.amount.toLocaleString('ar')} ${me.currency}</div></div>`).join('')}catch(x){toast(x.message,'er')}}
let fRv=null;
function rS(){fRv=null;document.getElementById('tps').innerHTML=`<div class="pg-h">تحويل <span>الأموال</span></div><div class="pg-s">أرسل أموالاً فورياً لأي حساب غولد ماستر</div><div class="fc"><div class="fc-t">🎯 المستلم</div><div class="fg"><label class="flab">طريقة البحث</label><select class="fin" id="sm" onchange="togM()"><option value="id">رقم الحساب</option><option value="phone">رقم الهاتف</option></select></div><div class="fg" id="fgI"><label class="flab">رقم الحساب</label><input class="fin ltr" id="sI" type="text" placeholder="GM000000" maxlength="8" oninput="lI()"></div><div class="fg" id="fgP" style="display:none"><label class="flab">رقم الهاتف</label><input class="fin ltr" id="sP" type="tel" placeholder="09XXXXXXXX" maxlength="10" oninput="lP()"></div><div class="rf" id="rF"><div class="rav">👤</div><div><div class="rnm" id="rFN"></div><div class="rid" id="rFI"></div></div><div class="rck">✓</div></div><div class="rnf" id="rNF">الحساب غير موجود</div></div><div class="fc"><div class="fc-t">💰 المبلغ والتفاصيل</div><div class="fg"><label class="flab">المبلغ (${me.currency})</label><input class="fin ltr" id="sA" type="number" placeholder="0" min="100" oninput="pA()"></div><div class="ap" id="aPv"><div class="apl">المبلغ المراد تحويله</div><div class="apv" id="aPvV"></div></div><div class="fg"><label class="flab">ملاحظة (اختياري)</label><input class="fin" id="sN" type="text" placeholder="اكتب ملاحظة..."></div></div><button class="ba" onclick="iTx()">🔐 متابعة للتأكيد</button>`}
function togM(){const m=document.getElementById('sm').value;document.getElementById('fgI').style.display=m==='id'?'block':'none';document.getElementById('fgP').style.display=m==='phone'?'block':'none';fRv=null;document.getElementById('rF').classList.remove('on');document.getElementById('rNF').classList.remove('on')}
let lT;function sLk(fn){clearTimeout(lT);lT=setTimeout(fn,500)}
async function lI(){const v=document.getElementById('sI').value.trim().toUpperCase();document.getElementById('rF').classList.remove('on');document.getElementById('rNF').classList.remove('on');if(v.length<6){fRv=null;return}sLk(async()=>{try{const u=await api('GET','/api/lookup?q='+v);fRv=u;shRv(u)}catch{fRv=null;document.getElementById('rF').classList.remove('on');document.getElementById('rNF').classList.add('on')}})}
async function lP(){const v=document.getElementById('sP').value.trim();document.getElementById('rF').classList.remove('on');document.getElementById('rNF').classList.remove('on');if(v.length<10){fRv=null;return}sLk(async()=>{try{const u=await api('GET','/api/lookup?phone='+v);fRv=u;shRv(u)}catch{fRv=null;document.getElementById('rF').classList.remove('on');document.getElementById('rNF').classList.add('on')}})}
function shRv(u){document.getElementById('rFN').textContent=u.name;document.getElementById('rFI').textContent=u.id+(u.city?' · '+u.city:'');document.getElementById('rF').classList.add('on');document.getElementById('rNF').classList.remove('on')}
function pA(){const v=parseInt(document.getElementById('sA').value),pr=document.getElementById('aPv');if(!v||v<1){pr.classList.remove('on');return}pr.classList.add('on');document.getElementById('aPvV').textContent=v.toLocaleString('ar')+' '+me.currency}
function iTx(){const amt=parseInt(document.getElementById('sA').value),note=document.getElementById('sN').value;if(!fRv){toast('اختر مستلماً أولاً','er');return}if(!amt||amt<100){toast('الحد الأدنى 100 ل.س','er');return}if(amt>me.balance){toast('رصيدك غير كافٍ','er');return}pTx={to:fRv.id,amount:amt,note};document.getElementById('pSb').textContent='إلى: '+fRv.name;document.getElementById('pAm').textContent=amt.toLocaleString('ar')+' '+me.currency;opPin()}
function rR(){document.getElementById('tpr').innerHTML=`<div class="pg-h">استلام <span>الأموال</span></div><div class="pg-s">شارك بياناتك مع المرسل</div><div class="fc" style="text-align:center"><div style="font-size:11px;color:var(--tx3);margin-bottom:12px;font-weight:600;text-transform:uppercase;letter-spacing:1px">رقم حسابك</div><div class="ab2"><div class="an">${me.id}</div></div><br><button class="cpb" onclick="cpId()">📋 نسخ رقم الحساب</button><div style="font-size:12px;color:var(--tx3);line-height:1.8">شارك هذا الرقم مع من يريد إرسال أموال لك<br>أو رقم هاتفك: <strong style="color:var(--g)">${me.phone}</strong></div></div><div class="fc"><div class="fc-t">🔍 تحقق من تحويل وارد</div><div class="fg"><label class="flab">رقم حساب المرسل</label><input class="fin ltr" id="ckI" type="text" placeholder="GM000000" maxlength="8"></div><button class="ba" onclick="ckI2()">بحث</button><div id="ckR" style="margin-top:12px"></div></div>`}
function cpId(){navigator.clipboard.writeText(me.id).then(()=>toast('تم نسخ رقم الحساب ✓','ok')).catch(()=>toast('تعذر النسخ','er'))}
async function ckI2(){const id=document.getElementById('ckI').value.trim().toUpperCase(),el=document.getElementById('ckR');if(!id){toast('أدخل رقم الحساب','er');return}try{const u=await api('GET','/api/lookup?q='+id);el.innerHTML=`<div class="rf on" style="margin-bottom:0"><div class="rav">👤</div><div><div class="rnm">${u.name}</div><div class="rid">${u.id}</div></div><div class="rck">✓</div></div>`}catch(x){el.innerHTML=`<div class="rnf on" style="margin-bottom:0">${x.message}</div>`}}
function rP(){document.getElementById('tpp').innerHTML=`<div class="pg-h">ملف <span>حسابي</span></div><div class="ph2"><div class="pav">👤</div><div><div class="pnm">${me.name}</div><div class="pid">${me.id}</div><div class="pst">نشط</div></div></div><div class="stt">معلومات الحساب</div><div class="ic"><div class="ir"><span class="irl">📱 رقم الهاتف</span><span class="irv">${me.phone}</span></div><div class="ir"><span class="irl">📍 المدينة</span><span class="irv">${me.city||'—'}</span></div><div class="ir"><span class="irl">💰 الرصيد</span><span class="irv" style="color:var(--g)">${me.balance.toLocaleString('ar')} ${me.currency}</span></div></div><div class="stt">الأمان والخصوصية</div><div class="sc"><div class="sct">🔑 تغيير كلمة المرور</div><div class="fg"><label class="flab">كلمة المرور الحالية</label><input class="fin ltr" id="pwo" type="password" placeholder="••••••••"></div><div class="fg"><label class="flab">الجديدة</label><input class="fin ltr" id="pwn" type="password" placeholder="••••••••"></div><div class="fg"><label class="flab">تأكيد</label><input class="fin ltr" id="pwc" type="password" placeholder="••••••••"></div><button class="ba" onclick="chPw()">💾 حفظ</button></div><div class="sc"><div class="sct">🔒 تغيير رمز PIN</div><div class="fg"><label class="flab">PIN الحالي</label><input class="fin ltr" id="pio" type="password" maxlength="4" placeholder="••••"></div><div class="fg"><label class="flab">PIN الجديد</label><input class="fin ltr" id="pi2" type="password" maxlength="4" placeholder="••••"></div><button class="ba" onclick="chPin()">💾 تغيير PIN</button></div><div class="stt">معلومات التطبيق</div><div class="ic"><div class="ir"><span class="irl">🏅 الشركة</span><span class="irv">غولد ماستر</span></div><div class="ir"><span class="irl">📍 الفرع</span><span class="irv">حلب — الباب</span></div><div class="ir"><span class="irl">⚡ الإصدار</span><span class="irv" style="color:var(--g)">v3.0</span></div></div><button class="bo rd" onclick="doLogout()" style="margin-top:12px">🚪 تسجيل الخروج</button>`}
async function chPw(){const o=document.getElementById('pwo').value,n=document.getElementById('pwn').value,c=document.getElementById('pwc').value;if(!o||!n||!c){toast('أكمل جميع الحقول','er');return}if(n!==c){toast('كلمتا المرور غير متطابقتين','er');return}try{await api('POST','/api/change-password',{old_password:o,new_password:n});toast('تم تغيير كلمة المرور ✓','ok');document.getElementById('pwo').value=document.getElementById('pwn').value=document.getElementById('pwc').value=''}catch(x){toast(x.message,'er')}}
async function chPin(){const o=document.getElementById('pio').value,n=document.getElementById('pi2').value;if(!o||!n){toast('أدخل PIN الحالي والجديد','er');return}if(n.length!==4||isNaN(n)){toast('PIN يجب 4 أرقام','er');return}try{await api('POST','/api/change-pin',{old_pin:o,new_pin:n});toast('تم تغيير PIN ✓','ok');document.getElementById('pio').value=document.getElementById('pi2').value=''}catch(x){toast(x.message,'er')}}
function opPin(){pinB='';upPd();document.getElementById('mPin').classList.add('on')}
function clPin(){document.getElementById('mPin').classList.remove('on');pinB='';pTx=null}
function pk(k){if(pinB.length>=4)return;pinB+=k;upPd()}
function pdl(){pinB=pinB.slice(0,-1);upPd()}
function upPd(){for(let i=1;i<=4;i++)document.getElementById('pd'+i).classList.toggle('on',i<=pinB.length)}
async function pcf(){if(pinB.length<4){toast('أدخل 4 أرقام','er');return}const btn=document.querySelector('#mPin .kb.cf');btn.textContent='…';btn.disabled=true;try{const r=await api('POST','/api/transfer',{to:pTx.to,amount:pTx.amount,note:pTx.note,pin:pinB});me.balance=r.new_balance;localStorage.setItem('gm',JSON.stringify(me));clPin();document.getElementById('sAm').textContent=pTx.amount.toLocaleString('ar')+' '+me.currency;document.getElementById('sSb').textContent='إلى '+r.receiver_name+'\nرصيدك المتبقي: '+r.new_balance.toLocaleString('ar')+' '+me.currency;document.getElementById('mSuc').classList.add('on');pTx=null}catch(x){toast(x.message,'er');pinB='';upPd()}finally{btn.textContent='✓';btn.disabled=false}}
function clSuc(){document.getElementById('mSuc').classList.remove('on');nTo('h')}
function toast(m,t='in'){const el=document.getElementById('toast');el.textContent=m;el.className='on '+t;clearTimeout(tT);tT=setTimeout(()=>el.classList.remove('on'),3200)}
(function(){if(tok&&me){document.getElementById('tbu').textContent=me.name.split(' ')[0];sV('vM');gT('h',document.querySelector('.bni'))}document.getElementById('lp').addEventListener('keydown',e=>{if(e.key==='Enter')doLogin()});document.getElementById('la').addEventListener('keydown',e=>{if(e.key==='Enter')document.getElementById('lp').focus()})})();
</script>
</body>
</html>"""

ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>غولد ماستر — لوحة التحكم</title>
<style>
:root{--g:#D4A843;--g2:#F0C560;--g3:#8B6914;--gg:rgba(212,168,67,.2);--ink:#07070C;--i2:#0F0F18;--i3:#161622;--i4:#1C1C2A;--gl:rgba(255,255,255,.04);--gl2:rgba(255,255,255,.07);--b:rgba(255,255,255,.07);--b2:rgba(255,255,255,.12);--tx:#EDE9E0;--tx2:#9E9894;--tx3:#4A4848;--ok:#00C896;--ok2:rgba(0,200,150,.1);--er:#FF4757;--er2:rgba(255,71,87,.1);--bl:#4A8FE2;--bl2:rgba(74,143,226,.1);--pu:#A855F7;--pu2:rgba(168,85,247,.1);--f:'Noto Kufi Arabic',system-ui,sans-serif;--r:12px;--rl:18px;--rx:24px}
*{margin:0;padding:0;box-sizing:border-box}html,body{height:100%;overflow:hidden;font-family:var(--f)}
body{background:var(--ink);color:var(--tx);display:flex}
body::before{content:'';position:fixed;inset:0;pointer-events:none;background:radial-gradient(ellipse 60% 40% at 85% 5%,rgba(212,168,67,.07),transparent 55%)}
.lov{position:fixed;inset:0;z-index:999;display:flex;align-items:center;justify-content:center;background:var(--ink);padding:20px}
.lov::before{content:'';position:absolute;inset:0;background:radial-gradient(ellipse 80% 60% at 60% 30%,rgba(212,168,67,.07),transparent 60%)}
.lbox{position:relative;z-index:1;background:var(--i2);border:1px solid var(--b2);border-radius:var(--rx);padding:44px 36px;width:100%;max-width:400px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.lico{width:78px;height:78px;border-radius:22px;background:linear-gradient(135deg,var(--g3),var(--g),var(--g2));display:flex;align-items:center;justify-content:center;font-size:36px;margin:0 auto 18px;box-shadow:0 0 40px rgba(212,168,67,.18),0 0 0 1px rgba(212,168,67,.3)}
.lnm{font-size:24px;font-weight:900;color:var(--g);letter-spacing:-.3px;margin-bottom:3px}
.lsb{font-size:11px;color:var(--tx3);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:6px}
.lrl{display:inline-flex;align-items:center;gap:5px;background:var(--pu2);border:1px solid rgba(168,85,247,.2);border-radius:99px;padding:4px 12px;font-size:11px;color:var(--pu);font-weight:700;margin-bottom:28px}
.li{width:100%;background:var(--i3);border:1.5px solid var(--b);border-radius:var(--r);padding:14px 16px;color:var(--tx);font-size:14px;font-family:var(--f);outline:none;direction:ltr;text-align:right;transition:all .3s;margin-bottom:12px}
.li:focus{border-color:var(--g);background:var(--i4);box-shadow:0 0 0 3px var(--gg)}.li::placeholder{color:var(--tx3)}
.lbtn{width:100%;background:linear-gradient(135deg,var(--g3),var(--g) 50%,var(--g2));border:none;border-radius:var(--r);padding:15px;color:#080808;font-size:14px;font-weight:800;font-family:var(--f);cursor:pointer;box-shadow:0 4px 20px var(--gg);transition:all .3s;position:relative;overflow:hidden}
.lbtn::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,transparent 40%,rgba(255,255,255,.1))}
.lbtn:hover{transform:translateY(-1px);box-shadow:0 6px 24px rgba(212,168,67,.28)}
.le{display:none;background:var(--er2);border:1px solid rgba(255,71,87,.22);border-radius:9px;padding:10px;color:var(--er);font-size:13px;margin-top:10px}
.layout{display:flex;height:100vh;width:100%;position:relative;z-index:1}
.sb{width:250px;flex-shrink:0;background:var(--i2);border-left:1px solid var(--b);display:flex;flex-direction:column;height:100vh;overflow-y:auto}.sb::-webkit-scrollbar{width:0}
.sb-hd{padding:22px 18px;border-bottom:1px solid var(--b)}
.sb-logo{display:flex;align-items:center;gap:11px}
.sb-ic{width:40px;height:40px;border-radius:11px;background:linear-gradient(135deg,var(--g3),var(--g));display:flex;align-items:center;justify-content:center;font-size:19px;box-shadow:0 4px 14px rgba(212,168,67,.22)}
.sb-nm{font-size:16px;font-weight:900;color:var(--g);letter-spacing:-.2px}.sb-sm{font-size:10px;color:var(--tx3);margin-top:2px;letter-spacing:.5px;text-transform:uppercase}
.sb-nav{padding:14px 12px;flex:1}
.ns{font-size:10px;color:var(--tx3);font-weight:700;letter-spacing:1.2px;padding:0 8px;margin:14px 0 7px;text-transform:uppercase}.ns:first-child{margin-top:0}
.ni{display:flex;align-items:center;gap:10px;padding:10px 11px;border-radius:11px;cursor:pointer;font-size:13px;font-weight:600;color:var(--tx2);transition:all .2s;border:1px solid transparent;margin-bottom:2px;position:relative}
.ni:hover{background:var(--gl);color:var(--tx)}
.ni.on{background:linear-gradient(135deg,rgba(212,168,67,.1),rgba(212,168,67,.04));border-color:rgba(212,168,67,.14);color:var(--g)}
.ni.on::before{content:'';position:absolute;right:0;top:25%;bottom:25%;width:3px;background:linear-gradient(to bottom,var(--g3),var(--g));border-radius:2px 0 0 2px}
.ni-ic{font-size:15px;width:26px;text-align:center}
.sb-ft{padding:14px 18px;border-top:1px solid var(--b)}
.sb-us{display:flex;align-items:center;gap:10px}
.sb-av{width:36px;height:36px;border-radius:10px;background:linear-gradient(135deg,var(--g3),var(--g));display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0}
.sb-un{font-size:13px;font-weight:700}.sb-ur{font-size:11px;color:var(--tx3)}
.sb-out{margin-right:auto;background:var(--er2);border:1px solid rgba(255,71,87,.15);color:var(--er);border-radius:7px;padding:5px 9px;font-size:11px;font-family:var(--f);cursor:pointer;transition:all .2s}
.sb-out:hover{background:rgba(255,71,87,.16)}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.mtb{padding:16px 26px;display:flex;align-items:center;justify-content:space-between;background:rgba(7,7,12,.96);backdrop-filter:blur(24px);border-bottom:1px solid var(--b);flex-shrink:0}
.mtb-t{font-size:19px;font-weight:900;letter-spacing:-.3px}
.mtb-r{display:flex;align-items:center;gap:10px}
.mtb-tm{font-size:12px;color:var(--tx3);font-weight:500}
.mtb-rf{background:var(--gl);border:1px solid var(--b);border-radius:8px;padding:7px 12px;color:var(--tx2);font-size:12px;font-weight:700;font-family:var(--f);cursor:pointer;transition:all .2s}
.mtb-rf:hover{background:var(--gl2)}
.mc{flex:1;overflow-y:auto;padding:24px}.mc::-webkit-scrollbar{width:3px}.mc::-webkit-scrollbar-thumb{background:var(--b2);border-radius:2px}
.pages .pg{display:none}.pages .pg.on{display:block;animation:pgi .3s both}
@keyframes pgi{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:22px}
.sc{background:var(--i2);border:1px solid var(--b);border-radius:var(--rl);padding:20px;transition:all .2s;cursor:default;position:relative;overflow:hidden}
.sc:hover{border-color:var(--b2);transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.sc-ic{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;margin-bottom:12px}
.sc-lb{font-size:11px;color:var(--tx3);font-weight:600;margin-bottom:5px;letter-spacing:.3px;text-transform:uppercase}
.sc-vl{font-size:24px;font-weight:900;letter-spacing:-.5px}
.sc-sb{font-size:11px;color:var(--tx3);margin-top:5px;font-weight:500}
.sc-g .sc-ic{background:var(--gg)}.sc-g .sc-vl{color:var(--g)}
.sc-ok .sc-ic{background:var(--ok2)}.sc-ok .sc-vl{color:var(--ok)}
.sc-bl .sc-ic{background:var(--bl2)}.sc-bl .sc-vl{color:var(--bl)}
.sc-pu .sc-ic{background:var(--pu2)}.sc-pu .sc-vl{color:var(--pu)}
.sc-er .sc-ic{background:var(--er2)}.sc-er .sc-vl{color:var(--er)}
.card{background:var(--i2);border:1px solid var(--b);border-radius:var(--rl);overflow:hidden;margin-bottom:18px}
.ch{padding:16px 20px;border-bottom:1px solid var(--b);display:flex;align-items:center;justify-content:space-between}
.ct{font-size:14px;font-weight:800;display:flex;align-items:center;gap:8px}
.ct::before{content:'';width:3px;height:16px;background:linear-gradient(to bottom,var(--g),var(--g3));border-radius:2px}
.cm{font-size:12px;color:var(--tx3);font-weight:500}
.sr{display:flex;align-items:center;gap:10px}
.si{background:var(--i3);border:1.5px solid var(--b);border-radius:9px;padding:9px 13px;color:var(--tx);font-size:13px;font-family:var(--f);outline:none;transition:all .3s;min-width:190px}
.si:focus{border-color:var(--g);box-shadow:0 0 0 2px var(--gg)}.si::placeholder{color:var(--tx3)}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{font-size:10px;color:var(--tx3);font-weight:700;padding:11px 14px;text-align:right;border-bottom:1px solid var(--b);white-space:nowrap;letter-spacing:.5px;text-transform:uppercase}
td{font-size:13px;padding:13px 14px;border-bottom:1px solid rgba(255,255,255,.03);transition:background .15s}
tr:last-child td{border-bottom:none}tr:hover td{background:var(--gl)}
.mn{font-family:monospace;color:var(--g);font-size:11px;letter-spacing:.5px;font-weight:700}
.bd{font-weight:700}.mu{font-size:11px;color:var(--tx3);font-weight:500}
.bg2{display:inline-flex;align-items:center;gap:4px;border-radius:6px;padding:4px 10px;font-size:10px;font-weight:700;font-family:var(--f);cursor:pointer;border:1px solid;transition:all .2s;white-space:nowrap}
.bg2::before{content:'';width:5px;height:5px;border-radius:50%}
.bg2-g{background:var(--gg);color:var(--g);border-color:rgba(212,168,67,.2)}.bg2-g::before{background:var(--g)}.bg2-g:hover{background:rgba(212,168,67,.18)}
.bg2-ok{background:var(--ok2);color:var(--ok);border-color:rgba(0,200,150,.2)}.bg2-ok::before{background:var(--ok)}.bg2-ok:hover{background:rgba(0,200,150,.18)}
.bg2-er{background:var(--er2);color:var(--er);border-color:rgba(255,71,87,.2)}.bg2-er::before{background:var(--er)}.bg2-er:hover{background:rgba(255,71,87,.18)}
.bg2-bl{background:var(--bl2);color:var(--bl);border-color:rgba(74,143,226,.2)}.bg2-bl::before{background:var(--bl)}.bg2-bl:hover{background:rgba(74,143,226,.18)}
.btn-p{background:linear-gradient(135deg,var(--g3),var(--g) 50%,var(--g2));border:none;border-radius:var(--r);padding:13px 22px;color:#080808;font-size:13px;font-weight:800;font-family:var(--f);cursor:pointer;transition:all .3s;box-shadow:0 4px 16px var(--gg);position:relative;overflow:hidden}
.btn-p::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,transparent 40%,rgba(255,255,255,.1))}
.btn-p:hover{transform:translateY(-1px);box-shadow:0 6px 22px rgba(212,168,67,.28)}.btn-p:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-s{background:var(--gl);border:1.5px solid var(--b2);border-radius:var(--r);padding:12px 18px;color:var(--tx2);font-size:13px;font-weight:700;font-family:var(--f);cursor:pointer;transition:all .25s}
.btn-s:hover{background:var(--gl2)}
.fg{display:flex;flex-direction:column;gap:6px;margin-bottom:13px}
.fl{font-size:10px;color:var(--g);font-weight:700;letter-spacing:.8px;text-transform:uppercase}
.fi{background:var(--i3);border:1.5px solid var(--b);border-radius:var(--r);padding:12px 15px;color:var(--tx);font-size:13px;font-family:var(--f);outline:none;transition:all .3s}
.fi:focus{border-color:var(--g);background:var(--i4);box-shadow:0 0 0 3px var(--gg)}.fi::placeholder{color:var(--tx3)}.fi.ltr{direction:ltr;text-align:left}
select.fi{appearance:none;cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23D4A843'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:left 13px center;padding-left:34px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:13px}
.g3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:13px}
.aok{display:none;background:var(--ok2);border:1px solid rgba(0,200,150,.22);border-radius:9px;padding:12px;color:var(--ok);font-size:13px;font-weight:600;margin-top:11px}
.aer{display:none;background:var(--er2);border:1px solid rgba(255,71,87,.22);border-radius:9px;padding:12px;color:var(--er);font-size:13px;font-weight:600;margin-top:11px}
.ufb{background:rgba(212,168,67,.06);border:1px solid rgba(212,168,67,.18);border-radius:11px;padding:13px 15px;display:none;align-items:center;gap:12px;margin-bottom:13px}
.ufb.on{display:flex}
.ufa{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,var(--g3),var(--g));display:flex;align-items:center;justify-content:center;font-size:17px}
.ufn{font-size:14px;font-weight:700}.ufbl{font-size:11px;color:var(--g);margin-top:2px;font-weight:600}
.mov{position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.82);backdrop-filter:blur(14px);display:flex;align-items:center;justify-content:center;opacity:0;pointer-events:none;transition:opacity .3s;padding:20px}
.mov.on{opacity:1;pointer-events:all}
.mb{background:var(--i2);border:1px solid var(--b2);border-radius:var(--rx);padding:28px;width:100%;max-width:500px;transform:scale(.95);transition:transform .35s cubic-bezier(.16,1,.3,1)}
.mov.on .mb{transform:scale(1)}
.mb-t{font-size:17px;font-weight:900;color:var(--g);margin-bottom:20px;display:flex;align-items:center;gap:8px;padding-bottom:13px;border-bottom:1px solid var(--b)}
.mb-cl{margin-right:auto;background:var(--gl2);border:none;color:var(--tx2);border-radius:7px;width:26px;height:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:13px}
.mb-cl:hover{background:var(--b)}
.mb-ac{display:flex;gap:10px;margin-top:18px}
.rg{display:grid;grid-template-columns:1fr 1fr;gap:13px}
#toast{position:fixed;top:20px;right:20px;z-index:500;background:var(--i3);border-radius:var(--r);padding:12px 16px;font-size:13px;font-weight:700;border:1px solid var(--b2);box-shadow:0 8px 32px rgba(0,0,0,.5);transform:translateX(120%);transition:transform .4s cubic-bezier(.16,1,.3,1);pointer-events:none;white-space:nowrap}
#toast.on{transform:translateX(0)}
#toast.ok{border-color:rgba(0,200,150,.35);color:var(--ok)}
#toast.er{border-color:rgba(255,71,87,.35);color:var(--er)}
#toast.in{border-color:rgba(212,168,67,.35);color:var(--g)}
.sp{display:inline-block;width:13px;height:13px;border:2px solid rgba(255,255,255,.15);border-top-color:var(--g);border-radius:50%;animation:spn .7s linear infinite;vertical-align:middle;margin-left:5px}
@keyframes spn{to{transform:rotate(360deg)}}
.emp{text-align:center;padding:44px;color:var(--tx3)}.emp-i{font-size:38px;margin-bottom:10px;opacity:.25}.emp-t{font-size:13px;font-weight:600}
@media(max-width:800px){.sb{display:none}.mc{padding:16px}.g2,.g3{grid-template-columns:1fr}.sg{grid-template-columns:1fr 1fr}.rg{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="lov" id="lov">
  <div class="lbox">
    <div class="lico">🏅</div>
    <div class="lnm">غولد ماستر</div>
    <div class="lsb">Gold Master · Admin Panel</div>
    <div class="lrl">👨‍💼 لوحة تحكم المدير</div>
    <input class="li" id="ak" type="password" placeholder="أدخل مفتاح الإدارة...">
    <button class="lbtn" onclick="doAdminLogin()">🔐 دخول إلى لوحة التحكم</button>
    <div class="le" id="le"></div>
  </div>
</div>

<div class="layout" id="lay" style="display:none">
  <div class="sb">
    <div class="sb-hd"><div class="sb-logo"><div class="sb-ic">🏅</div><div><div class="sb-nm">غولد ماستر</div><div class="sb-sm">Admin Dashboard</div></div></div></div>
    <div class="sb-nav">
      <div class="ns">الرئيسية</div>
      <div class="ni on" onclick="gP('dash',this)"><span class="ni-ic">📊</span>لوحة المعلومات</div>
      <div class="ns">إدارة العملاء</div>
      <div class="ni" onclick="gP('users',this)"><span class="ni-ic">👥</span>جميع الحسابات</div>
      <div class="ni" onclick="gP('add',this)"><span class="ni-ic">➕</span>إضافة عميل</div>
      <div class="ns">العمليات المالية</div>
      <div class="ni" onclick="gP('txs',this)"><span class="ni-ic">📋</span>سجل المعاملات</div>
      <div class="ni" onclick="gP('dep',this)"><span class="ni-ic">💰</span>إيداع وسحب</div>
      <div class="ns">التقارير</div>
      <div class="ni" onclick="gP('rep',this)"><span class="ni-ic">📈</span>التقارير والإحصائيات</div>
    </div>
    <div class="sb-ft"><div class="sb-us"><div class="sb-av">👨‍💼</div><div><div class="sb-un">المدير</div><div class="sb-ur">مدير النظام</div></div><button class="sb-out" onclick="doAdminLogout()">خروج</button></div></div>
  </div>
  <div class="main">
    <div class="mtb">
      <div class="mtb-t" id="pgtitle">لوحة المعلومات</div>
      <div class="mtb-r"><span class="mtb-tm" id="curT"></span><button class="mtb-rf" onclick="rfPage()">↻ تحديث</button></div>
    </div>
    <div class="mc">
      <div class="pages">
        <div class="pg on" id="pg-dash"></div>
        <div class="pg" id="pg-users"></div>
        <div class="pg" id="pg-add"></div>
        <div class="pg" id="pg-txs"></div>
        <div class="pg" id="pg-dep"></div>
        <div class="pg" id="pg-rep"></div>
      </div>
    </div>
  </div>
</div>

<div class="mov" id="editMov">
  <div class="mb">
    <div class="mb-t">✏️ تعديل بيانات العميل <button class="mb-cl" onclick="clEdit()">✕</button></div>
    <input type="hidden" id="eId">
    <div class="g2"><div class="fg"><label class="fl">الاسم الكامل</label><input class="fi" id="eNm" type="text"></div><div class="fg"><label class="fl">رقم الهاتف</label><input class="fi ltr" id="ePh" type="tel"></div></div>
    <div class="g2" style="margin-top:1px"><div class="fg"><label class="fl">المدينة</label><input class="fi" id="eCt" type="text"></div><div class="fg"><label class="fl">الحالة</label><select class="fi" id="eSt"><option value="نشط">✅ نشط</option><option value="موقوف">🚫 موقوف</option></select></div></div>
    <div class="fg" style="margin-top:1px"><label class="fl">كلمة مرور جديدة (اتركها فارغة للإبقاء)</label><input class="fi ltr" id="ePw" type="password" placeholder="كلمة مرور جديدة..."></div>
    <div id="eAlert"></div>
    <div class="mb-ac"><button class="btn-p" onclick="svEdit()">💾 حفظ التغييرات</button><button class="btn-s" onclick="clEdit()">إلغاء</button></div>
  </div>
</div>
<div id="toast"></div>

<script>
const AK='goldmaster-admin-2026',A='';let ak=localStorage.getItem('gma')||'',aU=[],aTx=[],cp='dash',tT;
function updT(){const n=new Date();document.getElementById('curT').textContent=n.toLocaleDateString('ar-SY')+' — '+n.toLocaleTimeString('ar-SY',{hour:'2-digit',minute:'2-digit'})}
setInterval(updT,1000);updT();
async function aApi(m,p,b){const o={method:m,headers:{'Content-Type':'application/json','X-Admin-Key':ak}};if(b)o.body=JSON.stringify(b);const r=await fetch(A+p,o),d=await r.json();if(!r.ok)throw new Error(d.error||'خطأ');return d}
function doAdminLogin(){const k=document.getElementById('ak').value,e=document.getElementById('le');if(k!==AK){e.textContent='⚠ مفتاح الإدارة غير صحيح';e.style.display='block';return}ak=k;localStorage.setItem('gma',k);document.getElementById('lov').style.display='none';document.getElementById('lay').style.display='flex';gP('dash',document.querySelector('.ni'))}
function doAdminLogout(){localStorage.removeItem('gma');ak='';document.getElementById('lov').style.display='flex';document.getElementById('lay').style.display='none';document.getElementById('ak').value=''}
function rfPage(){gP(cp,document.querySelector('.ni.on'))}
const pts={dash:'لوحة المعلومات',users:'جميع الحسابات',add:'إضافة عميل جديد',txs:'سجل المعاملات',dep:'إيداع وسحب',rep:'التقارير والإحصائيات'};
function gP(t,el){cp=t;document.querySelectorAll('.ni').forEach(b=>b.classList.remove('on'));el.classList.add('on');document.querySelectorAll('.pg').forEach(p=>p.classList.remove('on'));document.getElementById('pg-'+t).classList.add('on');document.getElementById('pgtitle').textContent=pts[t]||'';if(t==='dash')rDash();else if(t==='users')rUsers();else if(t==='add')rAdd();else if(t==='txs')rTxs();else if(t==='dep')rDep();else if(t==='rep')rRep()}
async function rDash(){const p=document.getElementById('pg-dash');p.innerHTML=`<div class="sg" id="ds"><div class="emp"><div class="emp-i">⏳</div></div></div><div class="card"><div class="ch"><div class="ct">آخر المعاملات</div><span class="cm" id="txm">—</span></div><div id="dtx"></div></div>`;try{const[u,tx]=await Promise.all([aApi('GET','/api/admin/users'),aApi('GET','/api/admin/all-transactions')]);aU=u;aTx=tx;const tot=u.reduce((a,x)=>a+x.balance,0),td=new Date().toISOString().slice(0,10),tdt=tx.filter(t=>(t.created_at||'').startsWith(td)),tr=tx.filter(t=>t.type==='transfer');document.getElementById('ds').innerHTML=`<div class="sc sc-g"><div class="sc-ic">👥</div><div class="sc-lb">إجمالي العملاء</div><div class="sc-vl">${u.length}</div><div class="sc-sb">حساب مسجل</div></div><div class="sc sc-ok"><div class="sc-ic">💰</div><div class="sc-lb">إجمالي الأرصدة</div><div class="sc-vl">${(tot/1000).toFixed(0)}k</div><div class="sc-sb">${tot.toLocaleString('ar')} ل.س</div></div><div class="sc sc-bl"><div class="sc-ic">🔄</div><div class="sc-lb">إجمالي التحويلات</div><div class="sc-vl">${tr.length}</div><div class="sc-sb">منذ البداية</div></div><div class="sc sc-pu"><div class="sc-ic">📅</div><div class="sc-lb">عمليات اليوم</div><div class="sc-vl">${tdt.length}</div><div class="sc-sb">معاملة اليوم</div></div>`;document.getElementById('txm').textContent=`آخر ${Math.min(tx.length,10)} من ${tx.length}`;rTxTbl('dtx',tx.slice(0,10))}catch(x){toast(x.message,'er')}}
function rTxTbl(eid,txs){const el=document.getElementById(eid);if(!txs.length){el.innerHTML='<div class="emp"><div class="emp-i">📋</div><div class="emp-t">لا توجد معاملات</div></div>';return}el.innerHTML=`<div class="tw"><table><thead><tr><th>النوع</th><th>من</th><th>إلى</th><th>المبلغ</th><th>الملاحظة</th><th>التاريخ</th></tr></thead><tbody>${txs.map(t=>`<tr><td><span class="bg2 ${t.type==='deposit'?'bg2-ok':t.type==='withdraw'?'bg2-er':'bg2-bl'}">${t.type==='deposit'?'إيداع':t.type==='withdraw'?'سحب':'تحويل'}</span></td><td class="bd">${t.from_name||'النظام'}</td><td class="bd">${t.to_name||'—'}</td><td style="color:var(--g);font-weight:800">${t.amount.toLocaleString('ar')} ل.س</td><td class="mu">${t.note||'—'}</td><td class="mu">${(t.created_at||'').slice(0,16)}</td></tr>`).join('')}</tbody></table></div>`}
async function rUsers(){const p=document.getElementById('pg-users');p.innerHTML=`<div class="card"><div class="ch"><div class="ct">قائمة العملاء</div><div class="sr"><input class="si" id="us" placeholder="🔍 بحث..." oninput="fusr(this.value)"><button class="btn-p" style="padding:9px 14px;font-size:12px" onclick="rUsers()">↻</button></div></div><div id="utbl"><div class="emp"><div class="emp-i">⏳</div></div></div></div>`;try{aU=await aApi('GET','/api/admin/users');ruTbl('')}catch(x){toast(x.message,'er')}}
function fusr(q){ruTbl(q)}
function ruTbl(q){const u=q?aU.filter(x=>x.name.includes(q)||x.id.includes(q.toUpperCase())||x.phone.includes(q)):aU,el=document.getElementById('utbl');if(!u.length){el.innerHTML='<div class="emp"><div class="emp-i">🔍</div><div class="emp-t">لا توجد نتائج</div></div>';return}el.innerHTML=`<div class="tw"><table><thead><tr><th>رقم الحساب</th><th>الاسم</th><th>الهاتف</th><th>الرصيد</th><th>المدينة</th><th>الحالة</th><th>الإجراءات</th></tr></thead><tbody>${u.map(x=>`<tr><td class="mn">${x.id}</td><td class="bd">${x.name}</td><td style="direction:ltr;text-align:right;font-size:12px">${x.phone}</td><td style="color:var(--g);font-weight:800">${parseFloat(x.balance).toLocaleString('ar')} ل.س</td><td class="mu">${x.city||'—'}</td><td><span class="bg2 ${x.status==='نشط'?'bg2-ok':'bg2-er'}">${x.status||'نشط'}</span></td><td style="display:flex;gap:5px;flex-wrap:wrap"><button class="bg2 bg2-g" onclick="opEdit('${x.id}')">✏️ تعديل</button><button class="bg2 bg2-bl" onclick="qDep('${x.id}','${x.name}')">💰 إيداع</button></td></tr>`).join('')}</tbody></table></div>`}
function rAdd(){document.getElementById('pg-add').innerHTML=`<div class="card"><div class="ch"><div class="ct">إنشاء حساب جديد</div></div><div style="padding:22px"><div class="g2"><div class="fg"><label class="fl">الاسم الكامل *</label><input class="fi" id="nNm" placeholder="اسم العميل الكامل"></div><div class="fg"><label class="fl">رقم الهاتف *</label><input class="fi ltr" id="nPh" type="tel" placeholder="09XXXXXXXX"></div></div><div class="g3" style="margin-top:1px"><div class="fg"><label class="fl">المدينة</label><input class="fi" id="nCt" placeholder="حلب - الباب"></div><div class="fg"><label class="fl">الرصيد الابتدائي</label><input class="fi ltr" id="nBl" type="number" placeholder="0" min="0"></div><div class="fg"><label class="fl">العملة</label><select class="fi" id="nCu"><option>ل.س</option><option>$</option></select></div></div><div class="g2" style="margin-top:1px"><div class="fg"><label class="fl">كلمة المرور *</label><input class="fi ltr" id="nPw" type="password" placeholder="كلمة المرور"></div><div class="fg"><label class="fl">رمز PIN (4 أرقام) *</label><input class="fi ltr" id="nPn" type="password" maxlength="4" placeholder="••••"></div></div><div style="margin-top:18px;display:flex;gap:10px"><button class="btn-p" id="addBtn" onclick="addU()">✅ إنشاء الحساب</button></div><div class="aok" id="aok"></div><div class="aer" id="aer"></div></div></div>`}
async function addU(){const b={name:document.getElementById('nNm').value.trim(),phone:document.getElementById('nPh').value.trim(),city:document.getElementById('nCt').value.trim(),balance:parseFloat(document.getElementById('nBl').value)||0,password:document.getElementById('nPw').value,pin:document.getElementById('nPn').value};if(!b.name||!b.phone||!b.password||!b.pin){toast('أكمل الحقول المطلوبة','er');return}if(b.pin.length!==4||isNaN(b.pin)){toast('PIN يجب 4 أرقام','er');return}const btn=document.getElementById('addBtn');btn.disabled=true;btn.innerHTML='جاري الإنشاء <span class="sp"></span>';const ok=document.getElementById('aok'),er=document.getElementById('aer');ok.style.display=er.style.display='none';try{const d=await aApi('POST','/api/admin/create-user',b);ok.textContent='✅ تم إنشاء الحساب! رقم الحساب: '+d.id;ok.style.display='block';toast('✅ تم: '+d.id,'ok');['nNm','nPh','nCt','nBl','nPw','nPn'].forEach(id=>document.getElementById(id).value='')}catch(x){er.textContent='⚠ '+x.message;er.style.display='block';toast(x.message,'er')}finally{btn.disabled=false;btn.innerHTML='✅ إنشاء الحساب'}}
async function rTxs(){const p=document.getElementById('pg-txs');p.innerHTML=`<div class="card"><div class="ch"><div class="ct">سجل جميع المعاملات</div><div class="sr"><input class="si" id="ts" placeholder="🔍 بحث..." oninput="fTxs(this.value)"><button class="btn-p" style="padding:9px 14px;font-size:12px" onclick="rTxs()">↻</button></div></div><div id="txfull"><div class="emp"><div class="emp-i">⏳</div></div></div></div>`;try{aTx=await aApi('GET','/api/admin/all-transactions');rTxTbl('txfull',aTx)}catch(x){toast(x.message,'er')}}
function fTxs(q){const txs=q?aTx.filter(t=>(t.from_name||'').includes(q)||(t.to_name||'').includes(q)):aTx;rTxTbl('txfull',txs)}
function rDep(){document.getElementById('pg-dep').innerHTML=`<div class="card"><div class="ch"><div class="ct">إيداع وسحب يدوي</div></div><div style="padding:22px"><div class="g2"><div class="fg"><label class="fl">رقم الحساب أو الهاتف</label><input class="fi ltr" id="dId" type="text" placeholder="GM000000 أو 09..." oninput="lkpD()"></div><div class="fg"><label class="fl">نوع العملية</label><select class="fi" id="dTp"><option value="deposit">📥 إيداع</option><option value="withdraw">📤 سحب</option></select></div></div><div class="ufb" id="dUfb"><div class="ufa">👤</div><div><div class="ufn" id="dUnm"></div><div class="ufbl" id="dUbl"></div></div></div><div class="g2"><div class="fg"><label class="fl">المبلغ (ل.س)</label><input class="fi ltr" id="dAm" type="number" placeholder="0" min="1"></div><div class="fg"><label class="fl">ملاحظة</label><input class="fi" id="dNt" placeholder="سبب العملية..."></div></div><div style="margin-top:18px"><button class="btn-p" id="depBtn" onclick="doDep()">✅ تنفيذ العملية</button></div><div class="aok" id="dok"></div><div class="aer" id="der"></div></div></div>`}
let dU=null,dT;
async function lkpD(){const v=document.getElementById('dId').value.trim();dU=null;document.getElementById('dUfb').classList.remove('on');if(v.length<6)return;clearTimeout(dT);dT=setTimeout(async()=>{try{const u=await aApi('GET','/api/admin/find-user?q='+encodeURIComponent(v.toUpperCase().startsWith('GM')?v.toUpperCase():v));dU=u;document.getElementById('dUnm').textContent=u.name+' ('+u.id+')';document.getElementById('dUbl').textContent='الرصيد: '+parseFloat(u.balance).toLocaleString('ar')+' ل.س';document.getElementById('dUfb').classList.add('on')}catch{dU=null}},500)}
function qDep(id,nm){gP('dep',document.querySelectorAll('.ni')[4]);setTimeout(()=>{document.getElementById('dId').value=id;lkpD()},300)}
async function doDep(){if(!dU){toast('ابحث عن العميل أولاً','er');return}const amt=parseFloat(document.getElementById('dAm').value),tp=document.getElementById('dTp').value,nt=document.getElementById('dNt').value;if(!amt||amt<=0){toast('أدخل مبلغاً صحيحاً','er');return}const btn=document.getElementById('depBtn');btn.disabled=true;btn.innerHTML='جاري التنفيذ <span class="sp"></span>';const ok=document.getElementById('dok'),er=document.getElementById('der');ok.style.display=er.style.display='none';try{const d=await aApi('POST','/api/admin/deposit',{user_id:dU.id,amount:amt,type:tp,note:nt});ok.textContent='✅ '+(tp==='deposit'?'تم الإيداع':'تم السحب')+' — الرصيد الجديد: '+d.new_balance.toLocaleString('ar')+' ل.س';ok.style.display='block';document.getElementById('dUbl').textContent='الرصيد: '+d.new_balance.toLocaleString('ar')+' ل.س';toast('✅ تمت العملية','ok');document.getElementById('dAm').value='';document.getElementById('dNt').value=''}catch(x){er.textContent='⚠ '+x.message;er.style.display='block';toast(x.message,'er')}finally{btn.disabled=false;btn.innerHTML='✅ تنفيذ العملية'}}
async function rRep(){const p=document.getElementById('pg-rep');p.innerHTML=`<div class="emp"><div class="emp-i">⏳</div></div>`;try{const[u,tx]=await Promise.all([aApi('GET','/api/admin/users'),aApi('GET','/api/admin/all-transactions')]);const tot=u.reduce((a,x)=>a+x.balance,0),tr=tx.filter(t=>t.type==='transfer'),dp=tx.filter(t=>t.type==='deposit'),wd=tx.filter(t=>t.type==='withdraw'),tt=tr.reduce((a,t)=>a+t.amount,0),td=dp.reduce((a,t)=>a+t.amount,0),tw=wd.reduce((a,t)=>a+t.amount,0),top=[...u].sort((a,b)=>b.balance-a.balance).slice(0,5),byD={};tx.forEach(t=>{const d=(t.created_at||'').slice(0,10);byD[d]=(byD[d]||0)+1});const dates=Object.entries(byD).sort((a,b)=>b[0]>a[0]?1:-1).slice(0,7);p.innerHTML=`<div class="sg"><div class="sc sc-g"><div class="sc-ic">💎</div><div class="sc-lb">إجمالي الأرصدة</div><div class="sc-vl">${tot.toLocaleString('ar')}</div><div class="sc-sb">ل.س</div></div><div class="sc sc-bl"><div class="sc-ic">🔄</div><div class="sc-lb">حجم التحويلات</div><div class="sc-vl">${tt.toLocaleString('ar')}</div><div class="sc-sb">${tr.length} عملية</div></div><div class="sc sc-ok"><div class="sc-ic">📥</div><div class="sc-lb">إجمالي الإيداعات</div><div class="sc-vl">${td.toLocaleString('ar')}</div><div class="sc-sb">${dp.length} إيداع</div></div><div class="sc sc-er"><div class="sc-ic">📤</div><div class="sc-lb">إجمالي السحوبات</div><div class="sc-vl">${tw.toLocaleString('ar')}</div><div class="sc-sb">${wd.length} سحب</div></div></div><div class="rg"><div class="card"><div class="ch"><div class="ct">🏆 أعلى الأرصدة</div></div><div class="tw"><table><thead><tr><th>#</th><th>الاسم</th><th>الرصيد</th></tr></thead><tbody>${top.map((x,i)=>`<tr><td style="font-size:18px">${['🥇','🥈','🥉','4️⃣','5️⃣'][i]}</td><td class="bd">${x.name}</td><td style="color:var(--g);font-weight:800">${parseFloat(x.balance).toLocaleString('ar')} ل.س</td></tr>`).join('')}</tbody></table></div></div><div class="card"><div class="ch"><div class="ct">📅 النشاط اليومي</div></div><div class="tw"><table><thead><tr><th>التاريخ</th><th>العمليات</th></tr></thead><tbody>${dates.map(([d,c])=>`<tr><td class="mn" style="color:var(--tx2)">${d}</td><td><span class="bg2 bg2-bl">${c} عملية</span></td></tr>`).join('')}</tbody></table></div></div></div>`}catch(x){toast(x.message,'er')}}
function opEdit(id){const u=aU.find(x=>x.id===id);if(!u)return;document.getElementById('eId').value=id;document.getElementById('eNm').value=u.name;document.getElementById('ePh').value=u.phone;document.getElementById('eCt').value=u.city||'';document.getElementById('eSt').value=u.status||'نشط';document.getElementById('ePw').value='';document.getElementById('eAlert').innerHTML='';document.getElementById('editMov').classList.add('on')}
function clEdit(){document.getElementById('editMov').classList.remove('on')}
async function svEdit(){const id=document.getElementById('eId').value,b={name:document.getElementById('eNm').value.trim(),phone:document.getElementById('ePh').value.trim(),city:document.getElementById('eCt').value.trim(),status:document.getElementById('eSt').value};const pw=document.getElementById('ePw').value;if(pw)b.password=pw;try{await aApi('POST','/api/admin/update-user/'+id,b);document.getElementById('eAlert').innerHTML='<div class="aok" style="display:block">✅ تم حفظ التغييرات</div>';toast('✅ تم التحديث','ok');setTimeout(()=>{clEdit();if(cp==='users')rUsers()},1200)}catch(x){document.getElementById('eAlert').innerHTML=`<div class="aer" style="display:block">⚠ ${x.message}</div>`}}
function toast(m,t='in'){const el=document.getElementById('toast');el.textContent=m;el.className='on '+t;clearTimeout(tT);tT=setTimeout(()=>el.classList.remove('on'),3500)}
(function(){if(ak===AK){document.getElementById('lov').style.display='none';document.getElementById('lay').style.display='flex';gP('dash',document.querySelector('.ni'))}document.getElementById('ak').addEventListener('keydown',e=>{if(e.key==='Enter')doAdminLogin()})})();
</script>
</body>
</html>"""

@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html; charset=utf-8")

@app.route("/admin")
@app.route("/admin.html")
def admin():
    return Response(ADMIN_HTML, mimetype="text/html; charset=utf-8")

init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🏅 Gold Master v3.0 running on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
