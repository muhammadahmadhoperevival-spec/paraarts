import os
import uuid
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key-before-going-live")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "paraarts.db")
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB per upload

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}
CATEGORIES = ["Vintage Coins", "Gemstones", "Antique Collections", "Art Paintings"]
CATEGORY_BLURBS = {
    "Vintage Coins": "Authentic collectible coins from around the world, graded and described honestly.",
    "Gemstones": "Natural, carefully sourced gemstones for collectors and jewellery makers.",
    "Antique Collections": "Curated antique pieces with history and character.",
    "Art Paintings": "Original paintings and fine art for homes and galleries.",
}
CATEGORY_ICONS = {
    "Vintage Coins": "coin",
    "Gemstones": "gem",
    "Antique Collections": "antique",
    "Art Paintings": "art",
}

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "admin_login"


class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    year = db.Column(db.String(50))
    origin = db.Column(db.String(100))
    condition = db.Column(db.String(100))
    description = db.Column(db.Text)
    image = db.Column(db.String(255))
    featured = db.Column(db.Boolean, default=False)
    in_stock = db.Column(db.Boolean, default=True)
    created = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def image_url(self):
        if self.image:
            return url_for("static", filename="uploads/" + self.image)
        return url_for("static", filename="img/placeholder-%s.svg" % CATEGORY_ICONS.get(self.category, "coin"))


class Inquiry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=False)
    country = db.Column(db.String(100))
    message = db.Column(db.Text, nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    handled = db.Column(db.Boolean, default=False)
    product = db.relationship("Product")


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Admin, int(user_id))


@app.context_processor
def inject_globals():
    return {"CATEGORIES": CATEGORIES, "CATEGORY_ICONS": CATEGORY_ICONS, "year": datetime.utcnow().year}


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return None
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    name = "%s_%s" % (uuid.uuid4().hex[:10], secure_filename(file_storage.filename))
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], name))
    return name


# ---------------------------------------------------------------- public pages
@app.route("/")
def index():
    featured = Product.query.filter_by(featured=True).order_by(Product.created.desc()).limit(8).all()
    counts = {c: Product.query.filter_by(category=c).count() for c in CATEGORIES}
    return render_template("index.html", featured=featured, counts=counts, blurbs=CATEGORY_BLURBS)


@app.route("/shop")
def shop():
    category = request.args.get("category", "")
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "new")
    query = Product.query
    if category in CATEGORIES:
        query = query.filter_by(category=category)
    if q:
        like = "%" + q + "%"
        query = query.filter(db.or_(Product.name.ilike(like), Product.description.ilike(like),
                                    Product.origin.ilike(like), Product.year.ilike(like)))
    if sort == "low":
        query = query.order_by(Product.price.asc())
    elif sort == "high":
        query = query.order_by(Product.price.desc())
    else:
        query = query.order_by(Product.created.desc())
    products = query.all()
    return render_template("shop.html", products=products, category=category, q=q, sort=sort)


@app.route("/product/<int:product_id>")
def product(product_id):
    p = db.get_or_404(Product, product_id)
    related = Product.query.filter(Product.category == p.category, Product.id != p.id).limit(4).all()
    return render_template("product.html", p=p, related=related)


@app.route("/inquire", methods=["POST"])
def inquire():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    country = request.form.get("country", "").strip()
    message = request.form.get("message", "").strip()
    product_id = request.form.get("product_id", type=int)
    back = request.form.get("back") or url_for("contact")
    if not name or "@" not in email or not message:
        flash("Please fill in your name, a valid email and a message.", "error")
        return redirect(back)
    db.session.add(Inquiry(name=name, email=email, country=country, message=message, product_id=product_id))
    db.session.commit()
    flash("Thank you! Your inquiry has been received. We will reply by email within 24 hours.", "success")
    return redirect(back)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


# ---------------------------------------------------------------------- admin
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        user = Admin.query.filter_by(username=request.form.get("username", "").strip()).first()
        if user and check_password_hash(user.password_hash, request.form.get("password", "")):
            login_user(user)
            return redirect(url_for("admin_dashboard"))
        flash("Wrong username or password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/admin")
@login_required
def admin_dashboard():
    products = Product.query.order_by(Product.created.desc()).all()
    inquiries = Inquiry.query.order_by(Inquiry.created.desc()).all()
    return render_template("admin_dashboard.html", products=products, inquiries=inquiries)


def fill_product(p):
    p.name = request.form.get("name", "").strip()
    p.category = request.form.get("category")
    p.price = request.form.get("price", type=float) or 0
    p.year = request.form.get("year", "").strip()
    p.origin = request.form.get("origin", "").strip()
    p.condition = request.form.get("condition", "").strip()
    p.description = request.form.get("description", "").strip()
    p.featured = bool(request.form.get("featured"))
    p.in_stock = bool(request.form.get("in_stock"))
    img = save_image(request.files.get("image"))
    if img:
        p.image = img


@app.route("/admin/product/new", methods=["GET", "POST"])
@login_required
def admin_new():
    if request.method == "POST":
        p = Product()
        fill_product(p)
        if not p.name or p.category not in CATEGORIES:
            flash("Name and category are required.", "error")
            return render_template("admin_form.html", p=p, new=True)
        db.session.add(p)
        db.session.commit()
        flash("Product added.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_form.html", p=Product(in_stock=True), new=True)


@app.route("/admin/product/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit(product_id):
    p = db.get_or_404(Product, product_id)
    if request.method == "POST":
        fill_product(p)
        db.session.commit()
        flash("Product updated.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_form.html", p=p, new=False)


@app.route("/admin/product/<int:product_id>/delete", methods=["POST"])
@login_required
def admin_delete(product_id):
    p = db.get_or_404(Product, product_id)
    Inquiry.query.filter_by(product_id=p.id).update({"product_id": None})
    db.session.delete(p)
    db.session.commit()
    flash("Product deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/inquiry/<int:inquiry_id>/toggle", methods=["POST"])
@login_required
def admin_inquiry_toggle(inquiry_id):
    i = db.get_or_404(Inquiry, inquiry_id)
    i.handled = not i.handled
    db.session.commit()
    return redirect(url_for("admin_dashboard") + "#inquiries")


# ------------------------------------------------------------------ seed data
SAMPLE = [
    ("1921 Morgan Silver Dollar", "Vintage Coins", 85, "1921", "United States", "Extremely Fine",
     "A classic Morgan silver dollar with strong detail on Liberty's portrait and a lustrous surface. 90% silver, 26.73 g.", True),
    ("1943 Walking Liberty Half Dollar", "Vintage Coins", 42, "1943", "United States", "Very Fine",
     "Iconic Walking Liberty design, 90% silver. Even toning and clear mint date.", True),
    ("Victorian Silver Crown 1889", "Vintage Coins", 120, "1889", "United Kingdom", "Fine",
     "Queen Victoria Jubilee Head silver crown with St George and the Dragon reverse.", True),
    ("Roman Denarius, Silver", "Vintage Coins", 160, "c. 100 AD", "Roman Empire", "Good Fine",
     "Authentic ancient silver denarius, sold with a certificate of authenticity.", True),
    ("Natural Blue Sapphire, 3.2 ct", "Gemstones", 340, "", "Sri Lanka", "Untreated",
     "Natural oval-cut blue sapphire with excellent clarity. Lab report available on request.", True),
    ("Emerald Cabochon, 4.5 ct", "Gemstones", 280, "", "Zambia", "Natural",
     "Deep green emerald cabochon, ideal for rings and pendants.", False),
    ("Antique Brass Pocket Compass", "Antique Collections", 95, "c. 1900", "England", "Good",
     "Working brass pocket compass with its original hinged lid and a handsome age patina.", True),
    ("Landscape in Oils, 24 x 18 in", "Art Paintings", 210, "2024", "Original", "New",
     "Original oil painting on canvas of a misty mountain valley. Signed by the artist and ships rolled in a tube.", True),
]


def init_db():
    with app.app_context():
        db.create_all()
        if not Admin.query.first():
            username = os.environ.get("ADMIN_USER", "admin")
            password = os.environ.get("ADMIN_PASSWORD", "ParaArts@2026")
            db.session.add(Admin(username=username, password_hash=generate_password_hash(password)))
        if not Product.query.first():
            for name, cat, price, year, origin, cond, desc, feat in SAMPLE:
                db.session.add(Product(name=name, category=cat, price=price, year=year, origin=origin,
                                       condition=cond, description=desc, featured=feat))
        db.session.commit()


init_db()

if __name__ == "__main__":
    app.run(debug=True)