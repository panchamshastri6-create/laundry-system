import re
from datetime import timedelta
from functools import wraps
from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt_identity, jwt_required
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from . import services as s
from .extensions import db
from .models import Customer, Garment, Order, OrderItem, Payment, Role, Service, User
from .utils import ApiError, now

api = Blueprint("api", __name__, url_prefix="/api")
ADMINS = ("SUPER_ADMIN", "MANAGER")
STAFF = ADMINS + ("FRONT_DESK", "LAUNDRY_STAFF")
OPS = STAFF + ("DELIVERY_STAFF",)

def ok(**kw):
    return jsonify(success=True, **kw)

def auth(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = db.session.get(User, int(get_jwt_identity()))
            if not u or not u.active:
                raise ApiError("Unauthorized", 401)
            if roles and u.role.name not in roles:
                raise ApiError("You do not have permission to do this", 403)
            g.user = u
            return f(*a, **k)
        return jwt_required()(w)
    return deco

def body():
    return request.get_json(silent=True) or {}

def order_or_404(oid):
    o = db.session.get(Order, oid)
    if o and g.user.role.name == "CUSTOMER" and o.customer.user_id != g.user.id:
        o = None
    if not o:
        raise ApiError("Order not found", 404)
    return o

def strong_password(p):
    if not (isinstance(p, str) and len(p) >= 8 and re.search(r"[A-Za-z]", p) and re.search(r"\d", p)):
        raise ApiError("Password must be at least 8 characters and include a letter and a number", 422)

# ---------- auth ----------
@api.post("/auth/login")
def login():
    d = body()
    email = str(d.get("email", "")).strip().lower()
    u = User.query.filter_by(email=email).first()
    if not u or not u.active or not check_password_hash(u.password_hash, str(d.get("password", ""))):
        s.audit("LOGIN_FAILED", "user", None, None, {"email": email[:120]})
        db.session.commit()
        raise ApiError("Invalid email or password", 401)
    s.audit("LOGIN", "user", u.id, u)
    db.session.commit()
    token = create_access_token(identity=str(u.id), additional_claims={"role": u.role.name})
    return ok(token=token, user=dict(id=u.id, name=u.name, email=u.email, role=u.role.name))

@api.post("/auth/logout")
@auth()
def logout():
    s.audit("LOGOUT", "user", g.user.id, g.user)  # tokens are stateless: the client discards its token
    db.session.commit()
    return ok(message="Logged out")

@api.get("/auth/me")
@auth()
def me():
    u = g.user
    return ok(user=dict(id=u.id, name=u.name, email=u.email, role=u.role.name))

@api.post("/users")
@auth(*ADMINS)
def create_user():
    d = body()
    role = d.get("role")
    if role not in [r.name for r in Role.query.all()]:
        raise ApiError("Invalid role", 422)
    if role in ("SUPER_ADMIN", "MANAGER") and g.user.role.name != "SUPER_ADMIN":
        raise ApiError("Only a super admin can create this role", 403)
    email = str(d.get("email", "")).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ApiError("Enter a valid email", 422)
    if User.query.filter_by(email=email).first():
        raise ApiError("A user with this email already exists", 409)
    strong_password(d.get("password"))
    if len(str(d.get("name", "")).strip()) < 2:
        raise ApiError("Name is required", 422)
    from .seed_data import make_user
    u = make_user(d["name"].strip(), email, role, d["password"], g.user.branch_id)
    s.audit("USER_CREATE", "user", u.id, g.user, {"role": role})
    db.session.commit()
    return ok(user=dict(id=u.id, email=u.email, role=role)), 201

# ---------- catalogue ----------
@api.get("/services")
@auth()
def services():
    from .models import ServicePrice
    keys = {x.id: x.key for x in Garment.query.all()}
    out = []
    for sv in Service.query.filter_by(active=True).all():
        prices = {keys[p.garment_id]: float(p.price) for p in ServicePrice.query.filter_by(service_id=sv.id)}
        out.append(dict(name=sv.name, prices=prices))
    return ok(services=out, garments={x.key: x.name for x in Garment.query.all()})

# ---------- customers ----------
def cust_dict(c, detail=False):
    d = dict(id=c.id, name=c.name, phone=c.phone, email=c.email, address=c.address)
    if detail:
        orders = c.orders
        billed = sum(s.m(o.total) for o in orders)
        paid = sum(s.paid_of(o.id) for o in orders)
        d.update(total_spent=float(paid), outstanding=float(billed - paid),
                 orders=[s.order_dict(o) for o in sorted(orders, key=lambda o: o.id, reverse=True)])
    return d

@api.post("/customers")
@auth(*STAFF)
def customer_create():
    d = body()
    c, created = s.get_or_create_customer(d.get("name"), d.get("phone"), g.user)
    db.session.commit()
    return ok(customer=cust_dict(c), created=created), 201 if created else 200

@api.get("/customers")
@auth(*STAFF)
def customer_list():
    q = request.args.get("q", "").strip().replace("%", "").replace("_", "")
    st = db.select(Customer).order_by(Customer.name)
    if q:
        st = st.where(db.or_(Customer.name.ilike(f"%{q}%"), Customer.phone.like(f"%{q}%")))
    p = db.paginate(st, page=request.args.get("page", 1, type=int), per_page=request.args.get("per_page", 20, type=int),
                    max_per_page=100, error_out=False)
    return ok(customers=[cust_dict(c) for c in p.items], page=p.page, pages=p.pages, total=p.total)

@api.get("/customers/<int:cid>")
@auth(*STAFF)
def customer_get(cid):
    c = db.session.get(Customer, cid)
    if not c:
        raise ApiError("Customer not found", 404)
    return ok(customer=cust_dict(c, True))

@api.put("/customers/<int:cid>")
@auth(*STAFF)
def customer_update(cid):
    c = db.session.get(Customer, cid)
    if not c:
        raise ApiError("Customer not found", 404)
    d = body()
    if "phone" in d:
        ph = s.norm_phone(d["phone"])
        other = Customer.query.filter_by(phone=ph).first()
        if other and other.id != c.id:
            raise ApiError("Another customer already uses this phone number", 409)
        c.phone = ph
    if "name" in d:
        if len(str(d["name"]).strip()) < 2:
            raise ApiError("Customer name is required", 422)
        c.name = d["name"].strip()[:120]
    for f in ("email", "address"):
        if f in d:
            setattr(c, f, (d[f] or "")[:255] or None)
    s.audit("CUSTOMER_UPDATE", "customer", c.id, g.user, {"fields": [k for k in d if k in ("name", "phone", "email", "address")]})
    db.session.commit()
    return ok(customer=cust_dict(c))

# ---------- orders ----------
@api.post("/orders")
@auth(*STAFF, "CUSTOMER")
def order_create():
    d = body()
    if g.user.role.name == "CUSTOMER":
        c = Customer.query.filter_by(user_id=g.user.id).first()
        if not c:
            raise ApiError("No customer profile is linked to this account", 403)
        d = {**d, "customer_id": c.id, "customer": None}
    o = s.create_order(d, g.user)
    db.session.commit()
    return ok(order=s.order_dict(o, True)), 201

@api.get("/orders")
@auth(*OPS, "CUSTOMER")
def order_list():
    st = db.select(Order).join(Customer).join(Service)
    if g.user.role.name == "CUSTOMER":
        st = st.where(Customer.user_id == g.user.id)
    status = request.args.get("status")
    if status:
        if status not in s.STAGES:
            raise ApiError("Invalid status", 422)
        st = st.where(Order.status == status)
    q = request.args.get("q", "").strip().replace("%", "").replace("_", "")
    if q:
        like = f"%{q}%"
        st = st.where(db.or_(Order.number.ilike(like), Customer.name.ilike(like), Customer.phone.like(like),
                             Service.name.ilike(like),
                             Order.items.any(OrderItem.garment.has(Garment.name.ilike(like)))))
    p = db.paginate(st.order_by(Order.id.desc()), page=request.args.get("page", 1, type=int),
                    per_page=request.args.get("per_page", 20, type=int), max_per_page=100, error_out=False)
    return ok(orders=[s.order_dict(o) for o in p.items], page=p.page, pages=p.pages, total=p.total)

@api.get("/orders/qr/<identifier>")
@auth(*OPS, "CUSTOMER")
def order_by_qr(identifier):
    o = Order.query.filter_by(number=identifier).first()
    return ok(order=s.order_dict(order_or_404(o.id) if o else _nf(), True))

def _nf():
    raise ApiError("Order not found", 404)

@api.get("/orders/<int:oid>")
@auth(*OPS, "CUSTOMER")
def order_get(oid):
    return ok(order=s.order_dict(order_or_404(oid), True))

@api.put("/orders/<int:oid>")
@auth(*STAFF)
def order_update(oid):
    o = order_or_404(oid)
    d = body()
    if o.status == "DELIVERED":
        raise ApiError("Delivered orders can no longer be edited", 409)
    for f in ("notes", "intake_notes"):
        if f in d:
            setattr(o, f, (d[f] or "")[:1000])
    if "express" in d or "discount" in d:
        express = bool(d.get("express", o.express))
        try:
            disc = s.m(d.get("discount", o.discount))
        except Exception:
            raise ApiError("Invalid discount", 422)
        if disc < 0 or disc > o.subtotal:
            raise ApiError("Discount must be between 0 and the order subtotal", 422)
        exc = s.m(o.subtotal * s.EXPRESS) if express else s.m(0)
        tax = s.m((o.subtotal + exc - disc) * s.TAX)
        total = o.subtotal + exc - disc + tax
        if total < s.paid_of(o.id):
            raise ApiError("New total is lower than the amount already paid. Refund first.", 409)
        o.express, o.discount, o.express_charge, o.tax, o.total = express, disc, exc, tax, total
    if "due_at" in d:
        from datetime import datetime
        try:
            o.due_at = datetime.fromisoformat(str(d["due_at"]).replace("Z", "")).replace(tzinfo=None)
        except ValueError:
            raise ApiError("Invalid due date", 422)
    s.audit("ORDER_UPDATE", "order", o.id, g.user, {"fields": [k for k in d]})
    db.session.commit()
    return ok(order=s.order_dict(o, True))

@api.delete("/orders/<int:oid>")
@auth(*ADMINS)
def order_delete(oid):
    o = order_or_404(oid)
    if o.payments:
        raise ApiError("Orders with payments cannot be deleted", 409)
    s.audit("ORDER_DELETE", "order", o.id, g.user, {"number": o.number})
    db.session.delete(o)
    db.session.commit()
    return ok(message="Order deleted")

@api.post("/orders/<int:oid>/advance")
@auth(*OPS)
def order_advance(oid):
    o = order_or_404(oid)
    i = s.STAGES.index(o.status)
    if i == len(s.STAGES) - 1:
        raise ApiError("Order is already delivered", 409)
    nxt = s.STAGES[i + 1]
    role = g.user.role.name
    if role == "DELIVERY_STAFF" and nxt not in ("OUT_FOR_DELIVERY", "DELIVERED"):
        raise ApiError("Delivery staff can only update delivery stages", 403)
    if role == "LAUNDRY_STAFF" and nxt in ("OUT_FOR_DELIVERY", "DELIVERED"):
        raise ApiError("Laundry staff cannot update delivery stages", 403)
    s.move(o, nxt, g.user)
    db.session.commit()
    return ok(order=s.order_dict(o, True))

@api.post("/orders/<int:oid>/qc-fail")
@auth(*STAFF)
def order_qc_fail(oid):
    o = order_or_404(oid)
    d = body()
    reason = str(d.get("reason", "")).strip()
    back = d.get("return_to", "WASHING")
    if o.status != "QUALITY_CHECK":
        raise ApiError("Only orders in Quality check can fail QC", 409)
    if len(reason) < 3:
        raise ApiError("Give a reason for the QC failure", 422)
    if back not in s.QC_RETURN_STAGES:
        raise ApiError("Invalid stage to return to", 422)
    s.move(o, back, g.user, f"QUALITY_CHECK_FAILED: {reason[:200]}", action="QUALITY_FAILURE")
    db.session.commit()
    return ok(order=s.order_dict(o, True))

@api.post("/orders/<int:oid>/payments")
@auth(*ADMINS, "FRONT_DESK")
def order_pay(oid):
    o = db.session.get(Order, oid, with_for_update=True)
    if not o:
        raise ApiError("Order not found", 404)
    d = body()
    s.add_payment(o, d.get("amount"), str(d.get("method", "CASH")).upper(), g.user)
    db.session.commit()
    return ok(order=s.order_dict(o, True)), 201

# ---------- dashboard ----------
@api.get("/dashboard")
@auth(*OPS)
def dashboard():
    off = timedelta(minutes=current_app.config["BUSINESS_UTC_OFFSET_MIN"])
    t = now()
    start = (t + off).replace(hour=0, minute=0, second=0, microsecond=0) - off
    end = start + timedelta(days=1)
    cnt = lambda *c: db.session.scalar(db.select(func.count(Order.id)).where(*c))
    open_ = Order.status != "DELIVERED"
    billed = db.session.scalar(db.select(func.coalesce(func.sum(Order.total), 0)))
    revenue = db.session.scalar(db.select(func.coalesce(func.sum(Payment.amount), 0)))
    pipe = dict(db.session.execute(db.select(Order.status, func.count(Order.id)).group_by(Order.status)).all())
    return ok(active=cnt(open_), due_today=cnt(open_, Order.due_at >= start, Order.due_at < end),
              overdue=cnt(open_, Order.due_at < t), ready=cnt(Order.status == "READY"),
              revenue=float(s.m(str(revenue))), outstanding=float(s.m(str(billed)) - s.m(str(revenue))),
              pipeline={k: pipe.get(k, 0) for k in s.STAGES})
