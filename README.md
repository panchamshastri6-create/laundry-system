# LaundryFlow (Phase 1: backend foundation)

Flask + SQLAlchemy + MySQL backend: JWT auth with 6 roles, customers, orders with server-side pricing, 11-stage workflow with history, QC failure, payments, dashboard, paginated search, QR identifiers (`LF-2026-000001`) and audit logs.

**Status:** the UI in `frontend/index.html` is the approved prototype and still uses browser localStorage. It is served at `/` by Flask but is **not yet wired to the API** (next step).

## Windows setup (PowerShell)
1. Install Python 3.11+ and MySQL 8 (MySQL Installer, "Server only"). Make sure the MySQL80 service is running.
2. Create the database and user (enter your root password when asked):
```
mysql -u root -p -e "CREATE DATABASE laundryflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER 'laundry_user'@'localhost' IDENTIFIED BY 'ChooseAStrongPassword1'; GRANT ALL ON laundryflow.* TO 'laundry_user'@'localhost';"
```
3. Install and configure:
```
cd LaundryFlow\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
4. Edit `backend\.env`: set the password inside `DATABASE_URL` and replace `SECRET_KEY` / `JWT_SECRET_KEY` with long random strings.
5. Create tables, load demo data, run:
```
flask db upgrade
python ..\database\seed.py
python run.py
```
Open http://127.0.0.1:5000 . Run tests: `python -m pytest` (uses in-memory SQLite, no MySQL needed).

If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## DEMO credentials (development only; password for all: `Demo@12345`)
admin@laundryflow.demo (SUPER_ADMIN), manager@, frontdesk1-3@, laundry1-5@, delivery1-2@, customer@ (all `@laundryflow.demo`).

## API (JSON; `Authorization: Bearer <token>`)
Errors: `{"success": false, "message": "..."}`.
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/users` (admins)
- `GET /api/services`
- `POST/GET /api/customers`, `GET/PUT /api/customers/<id>`
- `POST/GET /api/orders` (`?q=&status=&page=&per_page=`), `GET/PUT/DELETE /api/orders/<id>`, `GET /api/orders/qr/<LF-YYYY-NNNNNN>`
- `POST /api/orders/<id>/advance`, `POST /api/orders/<id>/qc-fail` (`reason`, `return_to`), `POST /api/orders/<id>/payments` (`amount`, `method`)
- `GET /api/dashboard`

## Layout
`backend/app` (models, routes, services, seed_data), `backend/migrations`, `backend/tests`, `database/seed.py`, `frontend/`, `uploads/`.

## Not yet built
Frontend-to-API wiring, rate limiting, file uploads, refunds, and Phase 2-4 modules (delivery, machines, inventory, complaints, analytics, multi-branch UI). Tokens are stateless, so logout is client-side plus an audit entry.
