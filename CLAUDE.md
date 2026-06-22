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

- `Vehicle` – central entity; has `track_token` (UUID) for public QR tracking, `qr_code_expiry` (1 year), vignette payment state, `fiscal_class` (A/B/C/D), `cv_class`, `usage_type`, `insurance_company` (text).
- `VehicleOwner` – one-to-one with `Vehicle`; holds mobile auth state (`session_version`, `current_device_id`, `expo_push_token`).
- `Fine` – fines issued against vehicles; `officer` field (username string) links to the issuing officer. `FineType` stores reusable infraction codes and amounts.
- `VignetteRate` / `PenaltyRate` – configurable pricing tables for annual road tax and late penalties.
- `Phone` – police department phones tracked with daily-rotating QR codes.
- `Insurance` / `InsuranceAccount` – `Insurance` is the company record; `InsuranceAccount` is the login account linked to it. `VehicleInsuranceAssignment` links vehicles to insurance accounts.
- `VehicleTransfer` – citizen-initiated ownership transfer requests with identity document upload.
- `DriverLicense` – driver's license record; `holder_name`, `holder_firstname`, `license_number`, `type_permis` (`temporaire`/`permanent`), `expiry_date`, `issue_date`, `status`, `points`. `is_expired` is a Python property.
- `PointReductionHistory` – log of license point reductions; `created_by` (username), `points_deducted`, `points_before`, `points_after`.
- `LicenseSetting` – singleton config for license system: `initial_points`, `temp_validity_months`. Use `LicenseSetting.get()`.
- `QRCodePayment` – records Smart Tech QR activation/renewal payments; `payment_type` (`activation`/`renewal`), `vehicle_id`, `amount`, `status`, `paid_at`, `recorded_by`.
- `SmartTechSetting` – key-value store for Smart Tech configuration (prices, simulator params, commission confirmations). Use `SmartTechSetting.get(key, default)` / `SmartTechSetting.set(key, value)`.

### Smart Tech system (`app/smart_tech.py`)

Separate Flask blueprint (`smart_tech_bp`, prefix `/smart-tech`) with its own login (`SmartTechAccount`). Templates are in `app/templates/smart_tech_*.html`.

Key pages:
- **Véhicules** (`smart_tech_vehicles.html`) – QR payment recording, receipt modal (activation splits amount in half: "Frais d'immatriculation numérique" + "Abonnement annuel"; renewal shows full amount as "Abonnement annuel").
- **Gestion des Véhicules** (`smart_tech_gestion_vehicules.html`) – CRUD for vehicles; uses `/api/vehicles/insurances` for insurance company select.
- **Renouvellement** (`smart_tech_renouvellement.html`) – list of vehicles with expired QR codes.
- **Agence Assurance** (`smart_tech_assurance.html`) – commission tracking per insurance company. Confirmation button only enabled from the 25th of each month.
- **Rapport** (`smart_tech_rapport.html`) – auto-generates report on load without showing the loading overlay (pass `false` to `generateReport(false)`).
- **Paramètres** (`smart_tech_parametres.html`) – simulator uses `sim_licenses_per_year` and `sim_insurance_rate` keys. "dont QR", "dont Licences", "dont Commissions" are sub-components of "Total revenus"; `Bénéfice cumulé = Total revenus − Total dépenses`.

### Licenses system

Routes in `app/routes.py`. `license_print()` accepts `?temporaire=1` to force TEMPORAIRE rendering and compute `computed_expiry` from `issue_date + relativedelta(months=temp_validity_months)` when no `expiry_date` is set. Uses `dateutil.relativedelta`.

### Admin — Historique d'Utilisation (`phone_usage.html` / `phone_usage.js`)

"Détails du Policier" modal has 3 tabs: **Informations personnelles**, **Historique amendes**, **Historique Réductions de points**. Data loaded from `/api/users/<id>/officer-history` (queries `Fine.officer` and `PointReductionHistory.created_by` by username). Both history tabs have De/À date filters defaulting to today; filtering is client-side.
