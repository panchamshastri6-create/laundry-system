"""Reference data shared by the demo seeder and the tests."""
from werkzeug.security import generate_password_hash
from .extensions import db
from .models import Branch, Garment, Role, Service, ServicePrice, User

ROLES = ["SUPER_ADMIN", "MANAGER", "FRONT_DESK", "LAUNDRY_STAFF", "DELIVERY_STAFF", "CUSTOMER"]
GARMENTS = {"shirt": "Shirt", "tshirt": "T-shirt", "jeans": "Jeans", "trouser": "Trouser",
            "jacket": "Jacket", "saree": "Saree", "bedsheet": "Bedsheet"}
PRICES = {"Wash & fold": [25, 20, 45, 35, 90, 80, 60], "Wash & iron": [40, 30, 60, 45, 110, 100, 80],
          "Dry cleaning": [90, 80, 130, 100, 250, 220, 180], "Ironing": [12, 10, 18, 15, 40, 35, 30]}

def seed_reference():
    if Role.query.first():
        return
    db.session.add(Branch(name="LaundryFlow Navrangpura", address="Navrangpura, Ahmedabad"))
    db.session.add_all(Role(name=r) for r in ROLES)
    db.session.add_all(Garment(key=k, name=n) for k, n in GARMENTS.items())
    db.session.flush()
    gl = {g.key: g.id for g in Garment.query.all()}
    for sname, prices in PRICES.items():
        s = Service(name=sname)
        db.session.add(s)
        db.session.flush()
        for key, price in zip(GARMENTS, prices):
            db.session.add(ServicePrice(service_id=s.id, garment_id=gl[key], price=price))
    db.session.commit()

def make_user(name, email, role, password, branch_id=1):
    u = User(name=name, email=email.lower(), password_hash=generate_password_hash(password),
             role_id=Role.query.filter_by(name=role).one().id, branch_id=branch_id)
    db.session.add(u)
    db.session.flush()
    return u
