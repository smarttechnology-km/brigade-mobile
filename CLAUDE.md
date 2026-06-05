# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend (Flask)

```bash
# Activate virtual environment first
source venv/bin/activate

# Run development server (port 5001)
python run.py

# Database migrations
flask db migrate -m "description"
flask db upgrade

# Reset and reinitialize DB
python init_db.py
```

The default admin account is created automatically on startup: `admin` / `admin123`.

### Mobile apps

```bash
# Police agent app (mobile/)
cd mobile && npm install
npx expo start

# Citizen app (mobile-citizen/)
cd mobile-citizen && npm install
npx expo start
```

Both apps default to the production backend (`https://brigade-mobile.onrender.com`). Set `REACT_APP_USE_LOCALHOST=true` to point at the local dev server instead.

### Deployment (Render)

```bash
# Production uses gunicorn via Procfile
gunicorn wsgi:app
```

## Architecture

### Backend

Flask app using the application factory pattern (`app/__init__.py` → `create_app()`). Five blueprints:

| Blueprint | Prefix | Purpose |
|---|---|---|
| `main_bp`, `vehicle_bp` | `/` | Web UI routes (Jinja2 templates) |
| `api_bp` | `/api` | REST API for mobile agents and web JS |
| `auth_bp` | `/auth` | Web session auth (Flask-Login) |
| `citizen_auth_bp` | `/api/auth` | Citizen mobile JWT auth (OTP via SMS) |
| `mobile_pay_bp` | `/pay` | Mobile payment flows (Huri Money) |

**Two separate auth systems run in parallel:**
- **Web users** (police, admin, judiciaire, insurance): Flask-Login sessions. `User` and `InsuranceAccount` share the same login form; session IDs are prefixed (`user:123` / `insurance:456`) to prevent ID collisions.
- **Citizen mobile app**: JWT (`Flask-JWT-Extended`). `VehicleOwner` registers/logs in via phone OTP. Tokens embed `session_version` and `device_id`; the blocklist loader in `__init__.py` rejects tokens when the session version changes or the device ID mismatches (single-device enforcement).

**Role-based access:**
- `administrateur` – full access across all islands
- `policier` / `judiciaire` – automatically filtered to their `country` field (Grande Comores, Anjouan, Moheli)
- `mobile_money_agent` – separate dashboard for vignette/mobile money flows
- `InsuranceAccount` – can only manage their own assigned vehicles

**Background jobs (APScheduler):**
- Every hour: process exonerated fines (auto-mark paid after 24 h)
- Daily 01:00: regenerate phone QR codes
- Daily 02:00: mark vehicles with expired QR codes as inactive

The scheduler is skipped when `FLASK_RUN_FROM_CLI` is set (prevents double-init during `flask db` commands).

### Database

- **Local dev**: SQLite (`police.db` at project root)
- **Production**: PostgreSQL (provisioned via `render.yaml`)

`create_app()` runs `db.create_all()` on startup and applies manual `ALTER TABLE` patches for SQLite when new columns are missing. For proper schema changes, use Flask-Migrate (`flask db migrate` / `flask db upgrade`).

All datetimes use Comoros timezone (UTC+3). Always use `now_comoros()` from `app/timezone_utils.py` instead of `datetime.utcnow()` or `datetime.now()`.

### Mobile apps

Both are Expo (React Native) projects in separate subdirectories (`mobile/`, `mobile-citizen/`), each with their own `package.json` and git history.

- **`mobile/`** – Police agent app: QR scan vehicles/phones, issue fines, submit photos, view reports.
- **`mobile-citizen/`** – Citizen app: OTP login via phone number, view fines, pay via Huri Money, manage vignette, request vehicle transfers.

API base URL logic: `BRIGADE_API_URL` env var → localhost if `REACT_APP_USE_LOCALHOST=true` → `https://brigade-mobile.onrender.com`.

The citizen app has a mock backend (`utils/mockBackend.js`) for offline development, enabled via `REACT_APP_USE_MOCK_BACKEND=true`.

### Key models

- `Vehicle` – central entity; has `track_token` (UUID) for public QR tracking, `qr_code_expiry` (1 year), vignette payment state, fiscal/CV class for rate calculation.
- `VehicleOwner` – one-to-one with `Vehicle`; holds mobile auth state (`session_version`, `current_device_id`, `expo_push_token`).
- `Fine` / `FineType` – fines issued against vehicles; `FineType` stores reusable infraction codes and amounts.
- `VignetteRate` / `PenaltyRate` – configurable pricing tables for annual road tax and late penalties.
- `Phone` – police department phones tracked with daily-rotating QR codes.
- `InsuranceAccount` – insurance company login linked to an `Insurance` record; can be assigned specific vehicles.
- `VehicleTransfer` – citizen-initiated ownership transfer requests with identity document upload.
