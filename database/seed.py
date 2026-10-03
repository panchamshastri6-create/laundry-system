"""Loads realistic demo data. Safe to run once on a freshly migrated database."""
import os, random, sys
from datetime import timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from app import create_app, services as s
from app.extensions import db
from app.models import Customer, Employee, Garment, Service, User
from app.seed_data import make_user, seed_reference
from app.utils import now

PWD = "Demo@12345"  # DEMO ONLY
STAFF = [("Rajesh Mehta", "admin", "SUPER_ADMIN"), ("Anita Shah", "manager", "MANAGER"),
         ("Pooja Solanki", "frontdesk1", "FRONT_DESK"), ("Harsh Vyas", "frontdesk2", "FRONT_DESK"),
         ("Nisha Chauhan", "frontdesk3", "FRONT_DESK"), ("Ramesh Thakor", "laundry1", "LAUNDRY_STAFF"),
         ("Dinesh Parmar", "laundry2", "LAUNDRY_STAFF"), ("Sunita Rathod", "laundry3", "LAUNDRY_STAFF"),
         ("Mahesh Prajapati", "laundry4", "LAUNDRY_STAFF"), ("Kavita Makwana", "laundry5", "LAUNDRY_STAFF"),
         ("Jignesh Bhatt", "delivery1", "DELIVERY_STAFF"), ("Hiren Rabari", "delivery2", "DELIVERY_STAFF")]
FIRST = ["Rahul", "Priya", "Amit", "Neha", "Kiran", "Sanjay", "Meera", "Vikram", "Divya", "Chirag", "Hetal", "Nilesh", "Bhavna",
         "Jay", "Komal", "Paresh", "Riddhi", "Tushar", "Urvi", "Yash", "Zalak", "Mitesh", "Foram", "Darshan", "Sejal"]
LAST = ["Patel", "Shah", "Desai", "Mehta", "Joshi", "Trivedi", "Parmar", "Solanki", "Modi", "Dave", "Pandya", "Thakkar"]

def main():
    app = create_app()
    with app.app_context():
        seed_reference()
        if User.query.first():
            sys.exit("Database already has users. Seeding skipped to avoid duplicates.")
        rnd = random.Random(2026)
        users = {}
        for i, (name, local, role) in enumerate(STAFF, 1):
            u = make_user(name, f"{local}@laundryflow.demo", role, PWD)
            db.session.add(Employee(user_id=u.id, code=f"EMP{i:03d}", department=role.replace("_", " ").title(),
                                    joined_on=(now() - timedelta(days=rnd.randint(90, 900))).date()))
            users.setdefault(role, []).append(u)
        custs, used = [], set()
        for i in range(25):
            phone = "9" + "".join(rnd.choice("0123456789") for _ in range(9))
            if phone in used:
                continue
            used.add(phone)
            c = Customer(name=f"{FIRST[i]} {rnd.choice(LAST)}", phone=phone, address=f"{rnd.randint(1, 120)}, Satellite, Ahmedabad")
            db.session.add(c)
            custs.append(c)
        db.session.flush()
        cu = make_user(custs[0].name, "customer@laundryflow.demo", "CUSTOMER", PWD)
        custs[0].user_id = cu.id
        services = [x.name for x in Service.query.all()]
        keys = [g.key for g in Garment.query.all()]
        for n in range(56):
            at = now() - timedelta(hours=rnd.randint(2, 240))
            fd = rnd.choice(users["FRONT_DESK"])
            items = [{"garment": k, "qty": rnd.randint(1, 5)} for k in rnd.sample(keys, rnd.randint(1, 4))]
            o = s.create_order({"customer_id": rnd.choice(custs).id, "service": rnd.choice(services), "items": items,
                                "express": rnd.random() < 0.15, "delivery_days": rnd.randint(1, 3),
                                "intake_notes": rnd.choice(["", "", "Small stain on collar", "Missing button on cuff"])}, fd, at)
            age_h = (now() - at).total_seconds() / 3600
            target = 10 if age_h > 100 and rnd.random() < .85 else rnd.randint(0, 9)
            for i in range(1, target + 1):
                who = rnd.choice(users["DELIVERY_STAFF"] if i >= 9 else users["LAUNDRY_STAFF"])
                s.move(o, s.STAGES[i], who, at=min(at + timedelta(hours=3 * i), now()))
            total = s.m(o.total)
            amount = total if target == 10 or rnd.random() < .4 else (s.m(total / 2) if rnd.random() < .5 else 0)
            if amount:
                s.add_payment(o, amount, rnd.choice(s.METHODS), fd, at=min(at + timedelta(hours=1), now()))
        db.session.commit()
        print("Seeded 12 staff, 25 customers, 56 orders. Demo password for every account:", PWD)

if __name__ == "__main__":
    main()
