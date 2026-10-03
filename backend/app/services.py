import re, uuid
from datetime import timedelta
from decimal import Decimal as D, ROUND_HALF_UP, InvalidOperation
from flask import request, has_request_context
from sqlalchemy import func
from .extensions import db
from .models import (AuditLog, Branch, Customer, Garment, Invoice, Order, OrderItem,
                     OrderStatusHistory, Payment, Service, ServicePrice)
from .utils import ApiError, now

STAGES = ["RECEIVED", "INSPECTION", "SORTING", "WASHING", "DRYING", "IRONING",
          "QUALITY_CHECK", "PACKAGING", "READY", "OUT_FOR_DELIVERY", "DELIVERED"]
QC_RETURN_STAGES = ["WASHING", "DRYING", "IRONING", "PACKAGING"]
METHODS = ["CASH", "UPI", "CARD", "ONLINE", "WALLET"]
TAX, EXPRESS = D("0.18"), D("0.50")

def m(x):
    return D(x).quantize(D("0.01"), ROUND_HALF_UP)

def audit(action, entity, entity_id=None, user=None, meta=None):
    ip = request.remote_addr if has_request_context() else None
    db.session.add(AuditLog(user_id=user.id if user else None, action=action, entity=entity,
                            entity_id=entity_id, meta=meta, ip=ip))

def norm_phone(p):
    digits = re.sub(r"\D", "", str(p or ""))[-10:]
    if len(digits) != 10:
        raise ApiError("Enter a valid 10-digit phone number", 422)
    return digits

def get_or_create_customer(name, phone, user=None):
    phone = norm_phone(phone)
    c = Customer.query.filter_by(phone=phone).first()
    if c:
        return c, False
    name = str(name or "").strip()
    if len(name) < 2:
        raise ApiError("Customer name is required", 422)
    c = Customer(name=name[:120], phone=phone)
    db.session.add(c)
    db.session.flush()
    audit("CUSTOMER_CREATE", "customer", c.id, user)
    return c, True

def paid_of(order_id):
    v = db.session.scalar(db.select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.order_id == order_id))
    return m(str(v))

def create_order(data, user, created_at=None):
    if data.get("customer_id"):
        c = db.session.get(Customer, data["customer_id"])
        if not c:
            raise ApiError("Customer not found", 404)
    else:
        cust = data.get("customer") or {}
        c, _ = get_or_create_customer(cust.get("name"), cust.get("phone"), user)
    svc = Service.query.filter_by(name=str(data.get("service")), active=True).first()
    if not svc:
        raise ApiError("Unknown service", 422)
    agg = {}
    for it in data.get("items") or []:
        try:
            q = int(it.get("qty"))
        except (TypeError, ValueError):
            raise ApiError("Quantity must be a whole number", 422)
        if not 1 <= q <= 100:
            raise ApiError("Quantity must be between 1 and 100", 422)
        agg[str(it.get("garment"))] = agg.get(str(it.get("garment")), 0) + q
    if not agg:
        raise ApiError("Add at least one garment", 422)
    lines = []
    for key, q in agg.items():
        g = Garment.query.filter_by(key=key).first()
        sp = g and ServicePrice.query.filter_by(service_id=svc.id, garment_id=g.id).first()
        if not sp:
            raise ApiError(f"'{key}' is not available for {svc.name}", 422)
        lines.append((g, q, sp.price))
    sub = m(sum(p * q for _, q, p in lines))
    express = bool(data.get("express"))
    exc = m(sub * EXPRESS) if express else m(0)
    try:
        disc = m(data.get("discount") or 0)
    except (InvalidOperation, ValueError):
        raise ApiError("Invalid discount", 422)
    if disc < 0 or disc > sub:
        raise ApiError("Discount must be between 0 and the order subtotal", 422)
    if disc and user.role.name == "CUSTOMER":
        raise ApiError("Customers cannot apply discounts", 403)
    tax = m((sub + exc - disc) * TAX)
    try:
        days = min(max(int(data.get("delivery_days") or 2), 1), 7)
    except (TypeError, ValueError):
        raise ApiError("Invalid delivery days", 422)
    at = created_at or now()
    due = at + (timedelta(days=days) / 2 if express else timedelta(days=days))
    branch_id = user.branch_id or Branch.query.order_by(Branch.id).first().id
    o = Order(number="TMP-" + uuid.uuid4().hex[:20], customer_id=c.id, branch_id=branch_id, service_id=svc.id,
              express=express, subtotal=sub, express_charge=exc, discount=disc, tax=tax,
              total=sub + exc - disc + tax, notes=(data.get("notes") or "")[:1000],
              intake_notes=(data.get("intake_notes") or "")[:1000], due_at=due,
              created_by=user.id, created_at=at, status="RECEIVED")
    db.session.add(o)
    db.session.flush()
    o.number = f"LF-{at.year}-{o.id:06d}"
    for g, q, p in lines:
        o.items.append(OrderItem(garment_id=g.id, qty=q, unit_price=p))
    db.session.add(OrderStatusHistory(order_id=o.id, previous_status=None, new_status="RECEIVED",
                                      changed_by=user.id, created_at=at))
    db.session.add(Invoice(order_id=o.id, number=f"INV-{at.year}-{o.id:06d}", issued_at=at))
    audit("ORDER_CREATE", "order", o.id, user, {"number": o.number})
    return o

def move(order, new_status, user, reason=None, at=None, action="STATUS_CHANGE"):
    prev = order.status
    order.status = new_status
    db.session.add(OrderStatusHistory(order_id=order.id, previous_status=prev, new_status=new_status,
                                      changed_by=user.id, reason=reason, created_at=at or now()))
    audit(action, "order", order.id, user, {"from": prev, "to": new_status, "reason": reason})

def add_payment(order, amount, method, user, at=None):
    try:
        amt = m(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise ApiError("Invalid payment amount", 422)
    if method not in METHODS:
        raise ApiError("Invalid payment method", 422)
    remaining = m(order.total) - paid_of(order.id)
    if amt <= 0:
        raise ApiError("Payment must be greater than zero", 422)
    if amt > remaining:
        raise ApiError(f"Payment exceeds the remaining balance of {remaining}", 422)
    p = Payment(order_id=order.id, amount=amt, method=method, received_by=user.id, created_at=at or now())
    db.session.add(p)
    db.session.flush()
    audit("PAYMENT", "order", order.id, user, {"amount": str(amt), "method": method})
    return p

def payment_status(order):
    paid = paid_of(order.id)
    return "PAID" if paid >= m(order.total) else "PARTIALLY_PAID" if paid > 0 else "PENDING"

def order_dict(o, detail=False):
    paid = paid_of(o.id)
    d = dict(id=o.id, number=o.number, qr_code=o.number, status=o.status, stage=STAGES.index(o.status),
             customer=dict(id=o.customer.id, name=o.customer.name, phone=o.customer.phone),
             service=o.service.name, express=o.express, created_at=o.created_at.isoformat(),
             due_at=o.due_at.isoformat(), overdue=o.status != "DELIVERED" and o.due_at < now(),
             subtotal=float(o.subtotal), express_charge=float(o.express_charge), discount=float(o.discount),
             tax=float(o.tax), total=float(o.total), paid=float(paid), remaining=float(m(o.total) - paid),
             payment_status=payment_status(o), item_count=sum(i.qty for i in o.items))
    if detail:
        d.update(notes=o.notes, intake_notes=o.intake_notes, invoice=o.invoice.number if o.invoice else None,
                 items=[dict(garment=i.garment.key, name=i.garment.name, qty=i.qty, unit_price=float(i.unit_price)) for i in o.items],
                 history=[dict(previous=h.previous_status, new=h.new_status, by=h.user.name if h.user else None,
                               reason=h.reason, at=h.created_at.isoformat()) for h in o.history],
                 payments=[dict(id=p.id, amount=float(p.amount), method=p.method, at=p.created_at.isoformat()) for p in o.payments])
    return d
