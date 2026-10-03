from sqlalchemy import UniqueConstraint, Index
from .extensions import db
from .utils import now

class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(30), unique=True, nullable=False)

class Branch(db.Model):
    __tablename__ = "branches"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    role = db.relationship("Role")

class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    department = db.Column(db.String(60))
    joined_on = db.Column(db.Date)
    user = db.relationship("User")

class Customer(db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(10), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class Garment(db.Model):
    __tablename__ = "garments"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)

class Service(db.Model):
    __tablename__ = "services"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

class ServicePrice(db.Model):
    __tablename__ = "service_prices"
    __table_args__ = (UniqueConstraint("service_id", "garment_id"),)
    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    garment_id = db.Column(db.Integer, db.ForeignKey("garments.id"), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)

class Order(db.Model):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_status_due", "status", "due_at"),)
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(30), unique=True, nullable=False, index=True)  # also the QR identifier
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="RECEIVED", index=True)
    express = db.Column(db.Boolean, default=False, nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    express_charge = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    discount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    tax = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text)
    intake_notes = db.Column(db.Text)
    due_at = db.Column(db.DateTime, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
    customer = db.relationship("Customer", backref="orders")
    service = db.relationship("Service")
    items = db.relationship("OrderItem", cascade="all, delete-orphan")
    history = db.relationship("OrderStatusHistory", cascade="all, delete-orphan", order_by="OrderStatusHistory.id")
    payments = db.relationship("Payment", cascade="all, delete-orphan", order_by="Payment.id")
    invoice = db.relationship("Invoice", cascade="all, delete-orphan", uselist=False)

class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    garment_id = db.Column(db.Integer, db.ForeignKey("garments.id"), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    garment = db.relationship("Garment")

class OrderStatusHistory(db.Model):
    __tablename__ = "order_status_history"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    previous_status = db.Column(db.String(20))
    new_status = db.Column(db.String(20), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    user = db.relationship("User")

class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    method = db.Column(db.String(20), nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now, nullable=False)

class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), unique=True, nullable=False)
    number = db.Column(db.String(30), unique=True, nullable=False)
    issued_at = db.Column(db.DateTime, default=now, nullable=False)

class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(40), nullable=False, index=True)
    entity = db.Column(db.String(40), nullable=False)
    entity_id = db.Column(db.Integer)
    meta = db.Column(db.JSON)
    ip = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=now, nullable=False, index=True)
