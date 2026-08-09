import os
import hmac
import sqlite3

from flask import Flask, request, jsonify, session, render_template, redirect, url_for, flash
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# SECRET_KEY: پێشتر os.urandom(24) بوو، واتە هەر جارێک ئەپلیکەیشن دەستپێدەکردەوە
# هەموو session بەکارهێنەرەکان دەبوونە batal. ئێستا لە ENV وەردەگیرێت و
# نرخێکی جێگیر بۆ گەشەپێدان هەیە (پێویستە لە production دا بگۆڕدرێت).
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")

# پێشتر CORS بۆ هەموو origin کراوە بوو لەگەڵ supports_credentials=True، ئەمەش
# ڕێگە بە هەر ماڵپەڕێکی دیکە دەدات داواکاری بە cookie ی بەکارهێنەرەکەت بنێرێت
# (CSRF-like). لەبەرئەوەی frontend و backend لە هەمان origin کاردەکەن پێویست
# بە CORS ناکات، تەنها بۆ گەشەپێدانی لۆکاڵ کراوەتەوە.
CORS(
    app,
    supports_credentials=True,
    origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:5000").split(","),
)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

CATEGORIES = ["ئەلکترۆنیات", "کارەباییات", "بیناسازی", "کەلوپەل"]
CATEGORY_LABELS = {c: c for c in CATEGORIES}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT,
            category TEXT,
            address TEXT,
            showroom TEXT,
            company TEXT,
            password_hash TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT,
            price REAL NOT NULL,
            image TEXT,
            FOREIGN KEY(shop_id) REFERENCES shops(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


# ---------------------------------------------------------------------------
# دروستکردنی داتای شیکاری (کەمترین/زۆرترین نرخ بۆ هەر کاڵایەک بەپێی ناو)
# ---------------------------------------------------------------------------
def build_price_analysis(conn):
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.category, p.price,
               s.id as shop_id, s.shop_name, s.showroom
        FROM products p JOIN shops s ON p.shop_id = s.id
        """
    ).fetchall()

    grouped = {}
    for r in rows:
        grouped.setdefault(r["name"], []).append(r)

    analysis = {}
    compare_items = []
    for name, items in grouped.items():
        cheapest = min(items, key=lambda x: x["price"])
        priciest = max(items, key=lambda x: x["price"])
        analysis[name] = {
            "min": {"price": cheapest["price"], "store_name": cheapest["shop_name"]},
            "max": {"price": priciest["price"], "store_name": priciest["shop_name"]},
        }
        compare_items.append(
            {
                "name": name,
                "count": len(items),
                "min": {
                    "price": cheapest["price"],
                    "shop": cheapest["shop_name"],
                    "showroom": cheapest["showroom"],
                },
                "max": {
                    "price": priciest["price"],
                    "shop": priciest["shop_name"],
                    "showroom": priciest["showroom"],
                },
                "diff": round(priciest["price"] - cheapest["price"], 2),
                "prices": [
                    {"shop": it["shop_name"], "showroom": it["showroom"], "price": it["price"]}
                    for it in sorted(items, key=lambda x: x["price"])
                ],
            }
        )

    return analysis, compare_items


# ---------------------------------------------------------------------------
# پەڕەکانی ناوەکی (پرۆژە بە template)
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/market")
def market():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT p.name, p.category, p.price, s.shop_name, s.showroom
        FROM products p JOIN shops s ON p.shop_id = s.id
        ORDER BY p.id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("market.html", rows=rows, category_labels=CATEGORY_LABELS)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        category = request.form.get("category", "").strip()
        address = request.form.get("address", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not phone or not password:
            flash("تکایە هەموو خانە پێویستەکان پڕبکەرەوە", "error")
            return render_template("register.html")

        conn = get_db()
        try:
            conn.execute(
                """INSERT INTO shops (shop_name, phone, email, category, address, password_hash)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, phone, email, category, address, generate_password_hash(password)),
            )
            conn.commit()
            flash("تۆمارکردنت سەرکەوتوو بوو، ئێستا دەتوانیت بچیتە ژوورەوە", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("ئەم ژمارە پەیوەندییە پێشتر تۆمارکراوە", "error")
            return render_template("register.html")
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        conn = get_db()
        shop = conn.execute("SELECT * FROM shops WHERE phone = ?", (phone,)).fetchone()
        conn.close()

        if shop and check_password_hash(shop["password_hash"], password):
            session.clear()
            session["user_id"] = shop["id"]
            session["username"] = shop["shop_name"]
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="ژمارە یان وشەی تێپەڕ هەڵەیە")

    return render_template("login.html")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    if request.method == "POST":
        # بۆ داواکاری fetch/JSON لە index.html (SPA)
        return jsonify({"success": True})
    flash("بە سەرکەوتوویی چوویتە دەرەوە", "success")
    return redirect(url_for("index"))


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        flash("تکایە سەرەتا بچۆ ژوورەوە", "error")
        return redirect(url_for("login"))

    conn = get_db()

    if request.method == "POST":
        item_name = request.form.get("item_name", "").strip()
        category = request.form.get("category", "").strip()
        price = request.form.get("price", "").strip()
        if item_name and price:
            try:
                price_val = float(price)
                conn.execute(
                    "INSERT INTO products (shop_id, name, category, price) VALUES (?, ?, ?, ?)",
                    (session["user_id"], item_name, category, price_val),
                )
                conn.commit()
                flash("کاڵاکە زیادکرا", "success")
            except ValueError:
                flash("نرخەکە دروست نییە", "error")

    analysis, _ = build_price_analysis(conn)
    users = conn.execute("SELECT shop_name as name, phone, email, category FROM shops ORDER BY id DESC").fetchall()
    my_products = conn.execute(
        "SELECT * FROM products WHERE shop_id = ? ORDER BY id DESC", (session["user_id"],)
    ).fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        analysis=analysis,
        users=users,
        my_products=my_products,
        category_labels=CATEGORY_LABELS,
    )


# ---------------------------------------------------------------------------
# پەڕەکانی بەڕێوەبەر (admin)
# ---------------------------------------------------------------------------
def require_admin():
    return session.get("role") == "admin"


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD):
            session.clear()
            session["role"] = "admin"
            session["username"] = ADMIN_USERNAME
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", error="ناوی بەکارهێنەر یان وشەی تێپەڕ هەڵەیە")
    return render_template("admin_login.html")


@app.route("/admin")
def admin_dashboard():
    if not require_admin():
        flash("تکایە وەک بەڕێوەبەر بچۆ ژوورەوە", "error")
        return redirect(url_for("admin_login"))

    conn = get_db()
    shops = conn.execute(
        """
        SELECT s.*, COUNT(p.id) as product_count
        FROM shops s LEFT JOIN products p ON p.shop_id = s.id
        GROUP BY s.id
        ORDER BY s.id DESC
        """
    ).fetchall()
    stats = {
        "shops": conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0],
        "products": conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "users": conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0],
    }
    conn.close()
    return render_template("admin.html", shops=shops, stats=stats, category_labels=CATEGORY_LABELS)


@app.route("/admin/compare")
def admin_compare():
    if not require_admin():
        flash("تکایە وەک بەڕێوەبەر بچۆ ژوورەوە", "error")
        return redirect(url_for("admin_login"))

    conn = get_db()
    _, items = build_price_analysis(conn)
    conn.close()
    return render_template("compare.html", items=items)


@app.route("/admin/shop/<int:sid>")
def admin_shop(sid):
    if not require_admin():
        flash("تکایە وەک بەڕێوەبەر بچۆ ژوورەوە", "error")
        return redirect(url_for("admin_login"))

    conn = get_db()
    shop = conn.execute("SELECT * FROM shops WHERE id = ?", (sid,)).fetchone()
    if not shop:
        conn.close()
        flash("ئەم فرۆشگایە نەدۆزرایەوە", "error")
        return redirect(url_for("admin_dashboard"))

    products = conn.execute("SELECT * FROM products WHERE shop_id = ? ORDER BY id DESC", (sid,)).fetchall()
    conn.close()
    return render_template("admin_shop.html", shop=shop, products=products, category_labels=CATEGORY_LABELS)


@app.route("/admin/shop/<int:sid>/products", methods=["POST"])
def admin_add_product(sid):
    if not require_admin():
        return redirect(url_for("admin_login"))

    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()
    conn = get_db()
    shop = conn.execute("SELECT * FROM shops WHERE id = ?", (sid,)).fetchone()
    if shop and name and price:
        try:
            price_val = float(price)
            conn.execute(
                "INSERT INTO products (shop_id, name, category, price) VALUES (?, ?, ?, ?)",
                (sid, name, shop["category"], price_val),
            )
            conn.commit()
            flash("کاڵا زیادکرا", "success")
        except ValueError:
            flash("نرخەکە دروست نییە", "error")
    conn.close()
    return redirect(url_for("admin_shop", sid=sid))


@app.route("/admin/products/<int:pid>/update", methods=["POST"])
def admin_update_product(pid):
    if not require_admin():
        return redirect(url_for("admin_login"))

    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if not product:
        conn.close()
        flash("کاڵاکە نەدۆزرایەوە", "error")
        return redirect(url_for("admin_dashboard"))

    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()
    if name and price:
        try:
            price_val = float(price)
            conn.execute("UPDATE products SET name = ?, price = ? WHERE id = ?", (name, price_val, pid))
            conn.commit()
            flash("نوێکرایەوە", "success")
        except ValueError:
            flash("نرخەکە دروست نییە", "error")
    shop_id = product["shop_id"]
    conn.close()
    return redirect(url_for("admin_shop", sid=shop_id))


@app.route("/admin/products/<int:pid>/delete", methods=["POST"])
def admin_delete_product(pid):
    if not require_admin():
        return redirect(url_for("admin_login"))

    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if product:
        shop_id = product["shop_id"]
        conn.execute("DELETE FROM products WHERE id = ?", (pid,))
        conn.commit()
        conn.close()
        flash("کاڵا سڕایەوە", "success")
        return redirect(url_for("admin_shop", sid=shop_id))
    conn.close()
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# API ـی JSON کە index.html (SPA) بەکاریدەهێنێت - هەمان ناوونیشانەکان
# وەک پێشتر پاراستراون، تەنها ناوی فەنکشنەکان گۆڕدراوە بۆ 'api_' هەتا
# ملمانێی url_for لەگەڵ پەڕەکانی سەرەوە دروست نەبێت، و ئێستا لەگەڵ
# schema ی یەکگرتوو کاردەکەن.
# ---------------------------------------------------------------------------
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.json or {}
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO shops (shop_name, phone, address, password_hash)
               VALUES (?, ?, ?, ?)""",
            (
                data.get("name"),
                data.get("phone"),
                data.get("location"),
                generate_password_hash(data.get("password") or ""),
            ),
        )
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "message": "ئەم ژمارە پێشتر تۆمارکراوە"})
    finally:
        conn.close()


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.json or {}
    conn = get_db()
    shop = conn.execute("SELECT * FROM shops WHERE phone = ?", (data.get("phone"),)).fetchone()
    conn.close()
    if shop and check_password_hash(shop["password_hash"], data.get("password") or ""):
        session.clear()
        session["user_id"] = shop["id"]
        session["username"] = shop["shop_name"]
        return jsonify(
            {
                "success": True,
                "seller": {
                    "id": shop["id"],
                    "name": shop["shop_name"],
                    "phone": shop["phone"],
                    "location": shop["address"],
                },
            }
        )
    return jsonify({"success": False, "message": "ژمارە یان وشەی تێپەڕ هەڵەیە"})


@app.route("/api/products", methods=["POST"])
def api_add_products():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "تکایە بچۆ ژوورەوە"})
    data = request.json or {}
    shop_id = session["user_id"]
    conn = get_db()
    for p in data.get("products", []):
        conn.execute(
            "INSERT INTO products (shop_id, name, category, price, image) VALUES (?, ?, ?, ?, ?)",
            (shop_id, p.get("name"), p.get("category"), p.get("price"), p.get("image")),
        )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.json or {}
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))
    if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD):
        session.clear()
        session["role"] = "admin"
        session["username"] = ADMIN_USERNAME
        return jsonify({"success": True})
    return jsonify({"success": False})


@app.route("/api/admin/data", methods=["GET"])
def api_admin_data():
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "دەستپێگەیشتن ڕەتکراوە"})
    conn = get_db()
    products = conn.execute(
        """
        SELECT p.id, p.name, p.category, p.price, p.image,
               s.shop_name as shop_name, s.phone, s.address as location
        FROM products p JOIN shops s ON p.shop_id = s.id
        ORDER BY p.id DESC
        """
    ).fetchall()
    conn.close()
    return jsonify({"success": True, "products": [dict(row) for row in products]})


@app.route("/api/admin/product/<int:pid>", methods=["DELETE"])
def api_delete_product(pid):
    if session.get("role") != "admin":
        return jsonify({"success": False, "message": "دەستپێگەیشتن ڕەتکراوە"})
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/session", methods=["GET"])
def api_session():
    if session.get("role") == "admin":
        return jsonify({"logged_in": True, "is_admin": True})
    if "user_id" in session:
        conn = get_db()
        user = conn.execute(
            "SELECT id, shop_name as name, phone, address as location FROM shops WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
        conn.close()
        if user:
            return jsonify({"logged_in": True, "seller": dict(user)})
    return jsonify({"logged_in": False})


if __name__ == "__main__":
    # بۆ production، debug=False بهێڵەرەوە و SECRET_KEY/ADMIN_PASSWORD لە ENV دابنێ
    app.run(debug=False)
