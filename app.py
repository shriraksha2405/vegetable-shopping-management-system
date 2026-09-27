from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, uuid, re
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key")
BASE_DIR=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "vegetable_shop.db"))
UPLOAD_FOLDER=os.path.join(BASE_DIR, "static", "images")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS={"png","jpg","jpeg","gif","webp","svg"}

def save_vegetable_image(file):
    if not file or not file.filename:
        return ""
    ext=file.filename.rsplit(".",1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Only PNG, JPG, JPEG, GIF, WEBP or SVG images are allowed.")
    filename=f"veg_{uuid.uuid4().hex}.{ext}"
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return filename

def delete_uploaded_image(filename):
    if not filename or filename.endswith((".svg",)) and filename in {"tomato.svg","potato.svg","onion.svg","carrot.svg","beans.svg","cabbage.svg"}:
        return
    path=os.path.join(UPLOAD_FOLDER, filename)
    if os.path.isfile(path):
        try: os.remove(path)
        except OSError: pass

def get_db():
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn=get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, phone TEXT,
      address TEXT, delivery_location TEXT, pincode TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

    CREATE TABLE IF NOT EXISTS admins(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      email TEXT UNIQUE NOT NULL, password TEXT NOT NULL);

    CREATE TABLE IF NOT EXISTS vegetables(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      category TEXT NOT NULL, price REAL NOT NULL CHECK(price>=0),
      stock REAL NOT NULL DEFAULT 0 CHECK(stock>=0),
      description TEXT, image TEXT);

    CREATE TABLE IF NOT EXISTS cart(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      vegetable_id INTEGER NOT NULL, quantity REAL NOT NULL CHECK(quantity>0),
      UNIQUE(user_id,vegetable_id),
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
      FOREIGN KEY(vegetable_id) REFERENCES vegetables(id) ON DELETE CASCADE);

    CREATE TABLE IF NOT EXISTS orders(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
      total_amount REAL NOT NULL, delivery_charge REAL NOT NULL,
      address TEXT NOT NULL, delivery_location TEXT NOT NULL, pincode TEXT NOT NULL, phone TEXT NOT NULL,
      status TEXT DEFAULT 'Pending', order_date TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id) REFERENCES users(id));

    CREATE TABLE IF NOT EXISTS order_items(
      id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
      vegetable_id INTEGER NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL,
      FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
      FOREIGN KEY(vegetable_id) REFERENCES vegetables(id));

    CREATE TABLE IF NOT EXISTS payments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER UNIQUE NOT NULL,
      user_id INTEGER NOT NULL, amount REAL NOT NULL, payment_method TEXT NOT NULL,
      transaction_id TEXT, payment_status TEXT NOT NULL,
      payment_date TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users(id));
    """)
    # Upgrade databases created by older versions of the project.
    user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "delivery_location" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN delivery_location TEXT")
    if "pincode" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN pincode TEXT")
    order_cols = {r[1] for r in conn.execute("PRAGMA table_info(orders)").fetchall()}
    if "delivery_location" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN delivery_location TEXT")
    if "pincode" not in order_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN pincode TEXT")

    if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]==0:
        conn.execute("INSERT INTO admins(name,email,password) VALUES(?,?,?)",
                     ("Administrator","admin@vegshop.com",generate_password_hash("admin123")))
    if conn.execute("SELECT COUNT(*) FROM vegetables").fetchone()[0]==0:
        data=[
          ("Tomato","Leafy/Vegetable",40,50,"Fresh red tomatoes","tomato.svg"),
          ("Potato","Root",35,80,"Fresh potatoes","potato.svg"),
          ("Onion","Root",45,60,"Fresh onions","onion.svg"),
          ("Carrot","Root",60,30,"Fresh carrots","carrot.svg"),
          ("Beans","Vegetable",70,25,"Fresh green beans","beans.svg"),
          ("Cabbage","Leafy",30,40,"Fresh cabbage","cabbage.svg")
        ]
        conn.executemany("INSERT INTO vegetables(name,category,price,stock,description,image) VALUES(?,?,?,?,?,?)",data)
    conn.commit(); conn.close()

def login_required():
    return "user_id" in session
def admin_required():
    return "admin_id" in session

@app.route("/")
def home():
    conn=get_db()
    q=request.args.get("q","").strip(); cat=request.args.get("category","").strip()
    sql="SELECT * FROM vegetables WHERE stock>0"; params=[]
    if q: sql+=" AND (name LIKE ? OR description LIKE ?)"; params += [f"%{q}%",f"%{q}%"]
    if cat: sql+=" AND category=?"; params.append(cat)
    vegetables=conn.execute(sql+" ORDER BY name",params).fetchall()
    cats=conn.execute("SELECT DISTINCT category FROM vegetables ORDER BY category").fetchall()
    conn.close()
    return render_template("home.html",vegetables=vegetables,categories=cats,q=q,cat=cat)

@app.route("/register",methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("name","").strip(); email=request.form.get("email","").strip().lower()
        password=request.form.get("password",""); phone=request.form.get("phone","").strip()
        email_ok = re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email)
        phone_ok = re.fullmatch(r"[6-9]\d{9}", phone)
        if not name: flash("Full name is required."); return redirect(url_for("register"))
        if not email_ok: flash("Enter a valid email address, e.g. name@example.com."); return redirect(url_for("register"))
        if not phone_ok: flash("Enter a valid 10-digit Indian phone number starting with 6-9."); return redirect(url_for("register"))
        if len(password)<8: flash("Password must be at least 8 characters."); return redirect(url_for("register"))
        conn=get_db()
        try:
            conn.execute("INSERT INTO users(name,email,password,phone) VALUES(?,?,?,?)",
                         (name,email,generate_password_hash(password),phone)); conn.commit()
            flash("Registration successful. Please login.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError: flash("Email already registered.")
        finally: conn.close()
    return render_template("register.html")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form["email"].strip().lower(); password=request.form["password"]
        conn=get_db(); user=conn.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone(); conn.close()
        if user and check_password_hash(user["password"],password):
            session["user_id"]=user["id"]; session["user_name"]=user["name"]; return redirect(url_for("home"))
        flash("Invalid customer email or password.")
    return render_template("login.html",admin=False)

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/cart/add/<int:vid>",methods=["POST"])
def add_cart(vid):
    if not login_required(): return redirect(url_for("login"))
    qty=float(request.form.get("quantity",1))
    conn=get_db(); veg=conn.execute("SELECT * FROM vegetables WHERE id=?",(vid,)).fetchone()
    if not veg or qty<=0 or qty>veg["stock"]: conn.close(); flash("Invalid quantity or insufficient stock."); return redirect(url_for("home"))
    row=conn.execute("SELECT * FROM cart WHERE user_id=? AND vegetable_id=?",(session["user_id"],vid)).fetchone()
    if row:
        newq=row["quantity"]+qty
        if newq>veg["stock"]: conn.close(); flash("Not enough stock."); return redirect(url_for("home"))
        conn.execute("UPDATE cart SET quantity=? WHERE id=?",(newq,row["id"]))
    else: conn.execute("INSERT INTO cart(user_id,vegetable_id,quantity) VALUES(?,?,?)",(session["user_id"],vid,qty))
    conn.commit(); conn.close(); flash("Added to cart."); return redirect(url_for("home"))

@app.route("/cart")
def cart():
    if not login_required(): return redirect(url_for("login"))
    conn=get_db()
    items=conn.execute("""SELECT c.id,c.quantity,v.*,(c.quantity*v.price) subtotal
                          FROM cart c JOIN vegetables v ON c.vegetable_id=v.id
                          WHERE c.user_id=?""",(session["user_id"],)).fetchall()
    conn.close()
    subtotal=sum(x["subtotal"] for x in items); delivery=0 if subtotal>=500 or subtotal==0 else 40
    return render_template("cart.html",items=items,subtotal=subtotal,delivery=delivery,total=subtotal+delivery)

@app.post("/cart/update/<int:cid>")
def update_cart(cid):
    if not login_required(): return redirect(url_for("login"))
    qty=float(request.form["quantity"]); conn=get_db()
    row=conn.execute("""SELECT c.*,v.stock FROM cart c JOIN vegetables v ON v.id=c.vegetable_id
                        WHERE c.id=? AND c.user_id=?""",(cid,session["user_id"])).fetchone()
    if row and qty>0 and qty<=row["stock"]: conn.execute("UPDATE cart SET quantity=? WHERE id=?",(qty,cid))
    else: flash("Invalid quantity.")
    conn.commit(); conn.close(); return redirect(url_for("cart"))

@app.post("/cart/remove/<int:cid>")
def remove_cart(cid):
    if not login_required(): return redirect(url_for("login"))
    conn=get_db(); conn.execute("DELETE FROM cart WHERE id=? AND user_id=?",(cid,session["user_id"])); conn.commit(); conn.close()
    return redirect(url_for("cart"))

@app.route("/checkout",methods=["GET","POST"])
def checkout():
    if not login_required(): return redirect(url_for("login"))
    conn=get_db(); items=conn.execute("""SELECT c.*,v.name,v.price,v.stock,(c.quantity*v.price) subtotal
        FROM cart c JOIN vegetables v ON v.id=c.vegetable_id WHERE c.user_id=?""",(session["user_id"],)).fetchall()
    user=conn.execute("SELECT * FROM users WHERE id=?",(session["user_id"],)).fetchone(); conn.close()
    subtotal=sum(i["subtotal"] for i in items); delivery=0 if subtotal>=500 or subtotal==0 else 40
    if not items: flash("Your cart is empty."); return redirect(url_for("home"))
    if request.method=="POST":
        address=request.form.get("address","").strip(); location=request.form.get("delivery_location","").strip()
        pincode=request.form.get("pincode","").strip(); phone=request.form.get("phone","").strip()
        method=request.form["payment_method"]
        if not address or not location: flash("Delivery address and location are required."); return redirect(url_for("checkout"))
        if not re.fullmatch(r"[6-9]\d{9}", phone): flash("Enter a valid 10-digit Indian phone number starting with 6-9."); return redirect(url_for("checkout"))
        if not re.fullmatch(r"\d{6}", pincode): flash("Enter a valid 6-digit delivery PIN code."); return redirect(url_for("checkout"))
        conn=get_db()
        for i in items:
            fresh=conn.execute("SELECT stock FROM vegetables WHERE id=?",(i["vegetable_id"],)).fetchone()
            if fresh["stock"]<i["quantity"]: conn.close(); flash(f"Insufficient stock for {i['name']}."); return redirect(url_for("cart"))
        cur=conn.execute("INSERT INTO orders(user_id,total_amount,delivery_charge,address,delivery_location,pincode,phone,status) VALUES(?,?,?,?,?,?,?,?)",
                          (session["user_id"],subtotal+delivery,delivery,address,location,pincode,phone,"Confirmed"))
        oid=cur.lastrowid
        for i in items:
            conn.execute("INSERT INTO order_items(order_id,vegetable_id,quantity,price) VALUES(?,?,?,?)",(oid,i["vegetable_id"],i["quantity"],i["price"]))
            conn.execute("UPDATE vegetables SET stock=stock-? WHERE id=?",(i["quantity"],i["vegetable_id"]))
        status="Paid" if method in ("UPI","Card") else "Pending"
        tx=str(uuid.uuid4()).replace("-","").upper()[:16] if method!="Cash on Delivery" else None
        conn.execute("""INSERT INTO payments(order_id,user_id,amount,payment_method,transaction_id,payment_status)
                        VALUES(?,?,?,?,?,?)""",(oid,session["user_id"],subtotal+delivery,method,tx,status))
        conn.execute("DELETE FROM cart WHERE user_id=?",(session["user_id"],)); conn.commit(); conn.close()
        return redirect(url_for("payment_success",oid=oid))
    return render_template("checkout.html",user=user,subtotal=subtotal,delivery=delivery,total=subtotal+delivery)

@app.route("/payment-success/<int:oid>")
def payment_success(oid):
    if not login_required(): return redirect(url_for("login"))
    conn=get_db(); order=conn.execute("""SELECT o.*,p.payment_method,p.payment_status,p.transaction_id,p.payment_date
      FROM orders o JOIN payments p ON p.order_id=o.id WHERE o.id=? AND o.user_id=?""",(oid,session["user_id"])).fetchone(); conn.close()
    return render_template("payment_success.html",order=order)

@app.route("/orders")
def orders():
    if not login_required(): return redirect(url_for("login"))
    conn=get_db(); rows=conn.execute("""SELECT o.*,p.payment_method,p.payment_status,p.transaction_id
      FROM orders o JOIN payments p ON p.order_id=o.id WHERE o.user_id=? ORDER BY o.id DESC""",(session["user_id"],)).fetchall(); conn.close()
    return render_template("orders.html",orders=rows)

@app.route("/admin/login",methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        email=request.form["email"].strip().lower(); password=request.form["password"]
        conn=get_db(); a=conn.execute("SELECT * FROM admins WHERE email=?",(email,)).fetchone(); conn.close()
        if a and check_password_hash(a["password"],password):
            session.clear(); session["admin_id"]=a["id"]; session["admin_name"]=a["name"]; return redirect(url_for("admin_dashboard"))
        flash("Invalid admin credentials.")
    return render_template("login.html",admin=True)

@app.route("/admin/logout")
def admin_logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/admin")
def admin_dashboard():
    if not admin_required(): return redirect(url_for("admin_login"))
    conn=get_db()
    stats={
      "vegetables":conn.execute("SELECT COUNT(*) FROM vegetables").fetchone()[0],
      "users":conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
      "orders":conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
      "revenue":conn.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE payment_status='Paid'").fetchone()[0]
    }
    conn.close(); return render_template("admin/dashboard.html",stats=stats)

@app.route("/admin/vegetables")
def admin_vegetables():
    if not admin_required(): return redirect(url_for("admin_login"))
    conn=get_db(); rows=conn.execute("SELECT * FROM vegetables ORDER BY id DESC").fetchall(); conn.close()
    return render_template("admin/vegetables.html",vegetables=rows)

@app.route("/admin/vegetable/add",methods=["GET","POST"])
def admin_add_vegetable():
    if not admin_required(): return redirect(url_for("admin_login"))
    if request.method=="POST":
        try:
            image=save_vegetable_image(request.files.get("image"))
            conn=get_db(); conn.execute("""INSERT INTO vegetables(name,category,price,stock,description,image)
                VALUES(?,?,?,?,?,?)""",(request.form["name"].strip(),request.form["category"].strip(),float(request.form["price"]),
                float(request.form["stock"]),request.form["description"].strip(),image)); conn.commit(); conn.close()
            flash("Vegetable added successfully.")
            return redirect(url_for("admin_vegetables"))
        except ValueError as e:
            flash(str(e))
        except Exception as e:
            flash("Could not add vegetable. Please check the entered values.")
    return render_template("admin/vegetable_form.html",veg=None)

@app.route("/admin/vegetable/edit/<int:vid>",methods=["GET","POST"])
def admin_edit_vegetable(vid):
    if not admin_required(): return redirect(url_for("admin_login"))
    conn=get_db(); veg=conn.execute("SELECT * FROM vegetables WHERE id=?",(vid,)).fetchone()
    if not veg:
        conn.close(); flash("Vegetable not found."); return redirect(url_for("admin_vegetables"))
    if request.method=="POST":
        try:
            new_image=save_vegetable_image(request.files.get("image"))
            image=new_image or veg["image"]
            conn.execute("""UPDATE vegetables SET name=?,category=?,price=?,stock=?,description=?,image=? WHERE id=?""",
              (request.form["name"].strip(),request.form["category"].strip(),float(request.form["price"]),float(request.form["stock"]),
               request.form["description"].strip(),image,vid)); conn.commit(); conn.close()
            if new_image and veg["image"] != new_image: delete_uploaded_image(veg["image"])
            flash("Vegetable updated successfully.")
            return redirect(url_for("admin_vegetables"))
        except ValueError as e:
            flash(str(e))
        except Exception:
            flash("Could not update vegetable. Please check the entered values.")
    conn.close(); return render_template("admin/vegetable_form.html",veg=veg)

@app.post("/admin/vegetable/delete/<int:vid>")
def admin_delete_vegetable(vid):
    if not admin_required(): return redirect(url_for("admin_login"))
    conn=get_db(); conn.execute("DELETE FROM vegetables WHERE id=?",(vid,)); conn.commit(); conn.close()
    return redirect(url_for("admin_vegetables"))

@app.route("/admin/orders")
def admin_orders():
    if not admin_required(): return redirect(url_for("admin_login"))
    conn=get_db(); rows=conn.execute("""SELECT o.*,u.name customer,p.payment_method,p.payment_status,p.transaction_id
      FROM orders o JOIN users u ON u.id=o.user_id JOIN payments p ON p.order_id=o.id ORDER BY o.id DESC""").fetchall(); conn.close()
    return render_template("admin/orders.html",orders=rows)

@app.post("/admin/order/status/<int:oid>")
def admin_order_status(oid):
    if not admin_required(): return redirect(url_for("admin_login"))
    status=request.form["status"]; conn=get_db(); conn.execute("UPDATE orders SET status=? WHERE id=?",(status,oid)); conn.commit(); conn.close()
    return redirect(url_for("admin_orders"))

@app.route("/admin/customers")
def admin_customers():
    if not admin_required(): return redirect(url_for("admin_login"))
    conn=get_db(); rows=conn.execute("SELECT id,name,email,phone,address,created_at FROM users ORDER BY id DESC").fetchall(); conn.close()
    return render_template("admin/customers.html",customers=rows)

@app.route("/admin/payments")
def admin_payments():
    if not admin_required(): return redirect(url_for("admin_login"))
    conn=get_db(); rows=conn.execute("""SELECT p.*,u.name customer FROM payments p JOIN users u ON u.id=p.user_id ORDER BY p.id DESC""").fetchall(); conn.close()
    return render_template("admin/payments.html",payments=rows)

@app.route("/admin/create-admin",methods=["GET","POST"])
def create_admin():
    if not admin_required(): return redirect(url_for("admin_login"))
    if request.method=="POST":
        name=request.form.get("name", "").strip()
        email=request.form.get("email", "").strip().lower()
        password=request.form.get("password", "")
        if not name:
            flash("Admin name is required.", "error")
            return redirect(url_for("create_admin"))
        if not re.fullmatch(r"[A-Za-z0-9._%+-]+@gmail\.com", email):
            flash("Please enter a valid Gmail address ending with @gmail.com.", "error")
            return redirect(url_for("create_admin"))
        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return redirect(url_for("create_admin"))
        try:
            conn=get_db()
            conn.execute("INSERT INTO admins(name,email,password) VALUES(?,?,?)",
                (name,email,generate_password_hash(password)))
            conn.commit(); conn.close()
            flash("New admin created.", "success")
        except sqlite3.IntegrityError:
            flash("Admin email already exists.", "error")
        return redirect(url_for("create_admin"))
    return render_template("admin/create_admin.html")

@app.get("/health")
def health():
    return {"status": "ok"}, 200

# Initialize the database when Gunicorn imports the Flask app.
init_db()

if __name__=="__main__":
    port=int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
