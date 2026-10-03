import pytest
from app import create_app
from app.extensions import db
from app.models import AuditLog, Customer
from app.seed_data import make_user, seed_reference

PW = "Demo@12345"

@pytest.fixture()
def client():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                      "SECRET_KEY": "t" * 32, "JWT_SECRET_KEY": "j" * 32})
    with app.app_context():
        db.create_all()
        seed_reference()
        for name, role in [("Admin", "SUPER_ADMIN"), ("Manager", "MANAGER"), ("Front", "FRONT_DESK"),
                           ("Laundry", "LAUNDRY_STAFF"), ("Driver", "DELIVERY_STAFF"), ("Cust", "CUSTOMER"), ("Other", "CUSTOMER")]:
            make_user(name, f"{role.lower()}{'2' if name == 'Other' else ''}@t.in", role, PW)
        c = Customer(name="Cust", phone="9825011234", user_id=6)
        db.session.add(c)
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()

def H(client, role):
    r = client.post("/api/auth/login", json={"email": f"{role}@t.in", "password": PW})
    return {"Authorization": "Bearer " + r.get_json()["token"]}

ORDER = {"customer": {"name": "Rahul Patel", "phone": "98250 11234"}, "service": "Wash & iron",
         "items": [{"garment": "shirt", "qty": 3}, {"garment": "trouser", "qty": 2}]}

def new_order(client, **extra):
    r = client.post("/api/orders", json={**ORDER, **extra}, headers=H(client, "front_desk"))
    assert r.status_code == 201, r.get_json()
    return r.get_json()["order"]

def go(client, oid, n, role="manager"):
    for _ in range(n):
        assert client.post(f"/api/orders/{oid}/advance", headers=H(client, role)).status_code == 200

def test_login_and_bad_login(client):
    assert client.post("/api/auth/login", json={"email": "admin@t.in".replace("admin", "super_admin"), "password": PW}).status_code == 200
    r = client.post("/api/auth/login", json={"email": "super_admin@t.in", "password": "wrong"})
    assert r.status_code == 401 and r.get_json()["success"] is False

def test_auth_required_and_password_hashed(client):
    assert client.get("/api/orders").status_code == 401
    from app.models import User
    assert PW not in User.query.first().password_hash

def test_role_permissions(client):
    o = new_order(client)
    assert client.delete(f"/api/orders/{o['id']}", headers=H(client, "laundry_staff")).status_code == 403
    assert client.post("/api/users", json={}, headers=H(client, "front_desk")).status_code == 403
    assert client.post(f"/api/orders/{o['id']}/payments", json={"amount": 10}, headers=H(client, "laundry_staff")).status_code == 403
    assert client.get("/api/dashboard", headers=H(client, "customer")).status_code == 403

def test_manager_cannot_create_admin(client):
    r = client.post("/api/users", json={"name": "Evil", "email": "e@t.in", "password": PW, "role": "SUPER_ADMIN"}, headers=H(client, "manager"))
    assert r.status_code == 403

def test_password_validation(client):
    r = client.post("/api/users", json={"name": "Asha", "email": "a@t.in", "password": "short", "role": "FRONT_DESK"}, headers=H(client, "super_admin"))
    assert r.status_code == 422

def test_customer_dedupe_and_update(client):
    h = H(client, "front_desk")
    r1 = client.post("/api/customers", json={"name": "Neha Mehta", "phone": "97270 66310"}, headers=h)
    r2 = client.post("/api/customers", json={"name": "Neha M", "phone": "9727066310"}, headers=h)
    assert r1.status_code == 201 and r2.status_code == 200 and r1.get_json()["customer"]["id"] == r2.get_json()["customer"]["id"]
    cid = r1.get_json()["customer"]["id"]
    assert client.put(f"/api/customers/{cid}", json={"phone": "9727066311"}, headers=h).status_code == 200
    assert client.post("/api/customers", json={"name": "X", "phone": "123"}, headers=h).status_code == 422

def test_order_totals_calculated_by_server(client):
    o = new_order(client, total=1, tax=0, subtotal=1, status="DELIVERED")
    assert o["subtotal"] == 210 and o["tax"] == 37.8 and o["total"] == 247.8
    assert o["status"] == "RECEIVED" and o["number"].startswith("LF-") and o["qr_code"] == o["number"]
    assert len(o["items"]) == 2 and o["history"][0]["new"] == "RECEIVED"

def test_order_validation(client):
    h = H(client, "front_desk")
    assert client.post("/api/orders", json={**ORDER, "items": []}, headers=h).status_code == 422
    assert client.post("/api/orders", json={**ORDER, "discount": 9999}, headers=h).status_code == 422
    assert client.post("/api/orders", json={**ORDER, "items": [{"garment": "shirt", "qty": -2}]}, headers=h).status_code == 422
    assert client.get("/api/orders/99999", headers=h).status_code == 404

def test_order_retrieval_qr_and_customer_scope(client):
    o = new_order(client)
    h = H(client, "manager")
    assert client.get(f"/api/orders/{o['id']}", headers=h).get_json()["order"]["number"] == o["number"]
    assert client.get(f"/api/orders/qr/{o['number']}", headers=h).get_json()["order"]["id"] == o["id"]
    assert client.get(f"/api/orders/{o['id']}", headers=H(client, "customer")).status_code == 200
    assert client.get(f"/api/orders/{o['id']}", headers=H(client, "customer2")).status_code == 404

def test_status_transitions_and_history(client):
    o = new_order(client)
    go(client, o["id"], 3, "laundry_staff")
    d = client.get(f"/api/orders/{o['id']}", headers=H(client, "manager")).get_json()["order"]
    assert d["status"] == "WASHING" and [h["new"] for h in d["history"]] == ["RECEIVED", "INSPECTION", "SORTING", "WASHING"]
    assert d["history"][1]["by"] == "Laundry"

def test_delivery_staff_limited(client):
    o = new_order(client)
    assert client.post(f"/api/orders/{o['id']}/advance", headers=H(client, "delivery_staff")).status_code == 403

def test_failed_qc(client):
    o = new_order(client)
    h = H(client, "manager")
    assert client.post(f"/api/orders/{o['id']}/qc-fail", json={"reason": "stain"}, headers=h).status_code == 409
    go(client, o["id"], 6)
    r = client.post(f"/api/orders/{o['id']}/qc-fail", json={"reason": "Stain still visible", "return_to": "WASHING"}, headers=h)
    d = r.get_json()["order"]
    assert d["status"] == "WASHING" and "Stain still visible" in d["history"][-1]["reason"]
    assert AuditLog.query.filter_by(action="QUALITY_FAILURE").count() == 1

def test_payments_partial_and_overpayment(client):
    o = new_order(client)
    h = H(client, "front_desk")
    r = client.post(f"/api/orders/{o['id']}/payments", json={"amount": 100, "method": "UPI"}, headers=h).get_json()["order"]
    assert r["payment_status"] == "PARTIALLY_PAID" and r["remaining"] == 147.8
    assert client.post(f"/api/orders/{o['id']}/payments", json={"amount": 200, "method": "CASH"}, headers=h).status_code == 422
    assert client.post(f"/api/orders/{o['id']}/payments", json={"amount": -5, "method": "CASH"}, headers=h).status_code == 422
    r = client.post(f"/api/orders/{o['id']}/payments", json={"amount": 147.8, "method": "CASH"}, headers=h).get_json()["order"]
    assert r["payment_status"] == "PAID" and len(r["payments"]) == 2

def test_search_and_pagination(client):
    new_order(client)
    new_order(client, customer={"name": "Priya Shah", "phone": "9879045521"}, service="Dry cleaning")
    h = H(client, "front_desk")
    f = lambda q: client.get(f"/api/orders?q={q}", headers=h).get_json()
    assert f("Priya")["total"] == 1 and f("98250")["total"] == 1 and f("Dry")["total"] == 1
    assert f("trouser")["total"] == 2 and f("LF-")["total"] == 2 and f("zzz")["total"] == 0
    assert client.get("/api/orders?per_page=1", headers=h).get_json()["pages"] == 2

def test_dashboard_from_database(client):
    a = new_order(client)
    new_order(client)
    client.post(f"/api/orders/{a['id']}/payments", json={"amount": 50, "method": "CASH"}, headers=H(client, "front_desk"))
    go(client, a["id"], 8)
    d = client.get("/api/dashboard", headers=H(client, "manager")).get_json()
    assert d["active"] == 2 and d["ready"] == 1 and d["revenue"] == 50 and d["outstanding"] == 445.6
    assert d["pipeline"]["READY"] == 1 and d["pipeline"]["RECEIVED"] == 1 and d["due_today"] == 0

def test_audit_trail_and_delete_rules(client):
    o = new_order(client)
    h = H(client, "manager")
    client.post(f"/api/orders/{o['id']}/payments", json={"amount": 10, "method": "CASH"}, headers=H(client, "front_desk"))
    assert client.delete(f"/api/orders/{o['id']}", headers=h).status_code == 409
    o2 = new_order(client)
    assert client.delete(f"/api/orders/{o2['id']}", headers=h).status_code == 200
    actions = {a.action for a in AuditLog.query.all()}
    assert {"LOGIN", "ORDER_CREATE", "PAYMENT", "ORDER_DELETE"} <= actions
