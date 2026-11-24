# Fish Business Daily Journal — Backend

A backend API for an Android application that helps a fish shop owner maintain a complete daily business journal.

Built with **FastAPI, SQLAlchemy 2, Pydantic v2, and Alembic**. Uses SQLite by default and supports PostgreSQL through `DATABASE_URL`.

The application manages daily fish purchases, stock, hotel sales, supplier payments, hotel payments, outstanding balances, and historical business records.

## Features

- Daily journal with opening and closing stock.
- Fish and supplier purchase records.
- Hotel fish sales with configurable rates.
- Separate supplier and hotel payment records.
- Supplier and hotel opening balances.
- Individual account ledgers and running balances.
- Monthly hotel summaries.
- Dashboard and historical journal records.
- Stock validation and business-rule enforcement.
- Single-owner authentication using JWT.
- Database migrations using Alembic.

## Technology Stack

| Component | Technology |
|---|---|
| Language | Python |
| API framework | FastAPI |
| ORM | SQLAlchemy 2 |
| Validation | Pydantic v2 |
| Database | SQLite / PostgreSQL |
| Migrations | Alembic |
| Authentication | JWT |
| Password hashing | scrypt |
| Testing | pytest |

## Getting Started

### Requirements

- Python 3.10 or newer (use a version supported by the project's dependencies).
- pip
- Git

### Ubuntu / Linux

Clone the repository:

```bash
git clone https://github.com/danishskh70/fish-journal.git
cd fish-journal
```

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the environment file:

```bash
cp .env.example .env
```

Generate a secure JWT secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Add the generated secret to `.env`:

```env
JWT_SECRET=your_generated_secret_here
```

Load the environment variables into your terminal:

```bash
set -a
source .env
set +a
```

Run database migrations:

```bash
alembic upgrade head
```

Create the owner account:

```bash
python -m app.cli create-owner --username owner
```

Start the API:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Windows CMD

Create and activate a virtual environment:

```cmd
python -m venv venv
venv\Scripts\activate
```

Install dependencies:

```cmd
pip install -r requirements.txt
```

Create the environment file:

```cmd
copy .env.example .env
```

Generate a JWT secret:

```cmd
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

Set the secret in CMD:

```cmd
set JWT_SECRET=your_generated_secret_here
```

Run migrations and create the owner:

```cmd
alembic upgrade head
python -m app.cli create-owner --username owner
```

Start the server:

```cmd
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For PowerShell, use:

```powershell
$env:JWT_SECRET="your_generated_secret_here"
```

The application uses SQLite by default. The first migration creates the database schema.

## Environment Configuration

Configuration is managed through environment variables.

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./fish_journal.db` | Database connection |
| `JWT_SECRET` | Required | Secret used for JWT signing |
| `ACCESS_TOKEN_MINUTES` | `15` | Access-token lifetime |
| `REFRESH_TOKEN_DAYS` | `30` | Refresh-token lifetime |
| `LOGIN_MAX_ATTEMPTS` | `5` | Maximum failed login attempts |
| `LOGIN_LOCK_MINUTES` | `15` | Login lock duration |
| `AUTH_DISABLED` | `false` | Disables authentication for local development only |
| `CORS_ORIGINS` | `*` | Allowed web origins |
| `ENABLE_DOCS` | `false` | Enables Swagger documentation |

Generate a JWT secret of at least 32 characters.

**Never commit your actual `.env` file or JWT secret to GitHub.**

### PostgreSQL Configuration

To use PostgreSQL instead of SQLite, configure:

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

Use credentials appropriate for your database provider.

## Running Tests

Run the complete test suite:

```bash
python -m pytest -q
```

The project includes tests for important business rules and database migrations.

## API Documentation

The API uses the `/api/v1` prefix.

Swagger documentation is disabled by default.

To enable it locally, configure:

```env
ENABLE_DOCS=true
```

Restart the application and visit:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

An `openapi.json` file is also included for Flutter API client integration.

## Authentication

The application supports one shop owner account. It is not a multi-user or staff-management system.

Authentication uses:

- Password hashing with scrypt.
- JWT access tokens (15 minutes).
- Rotating refresh tokens (30 days).
- Server-side refresh-token storage.
- Refresh-token reuse detection.
- Session revocation after password changes.
- Login protection after repeated failed attempts.

### Authentication Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/auth/login` | Owner login |
| POST | `/api/v1/auth/refresh` | Refresh tokens |
| POST | `/api/v1/auth/logout` | Revoke refresh token |
| GET | `/api/v1/auth/me` | Check authenticated owner |
| POST | `/api/v1/auth/change-password` | Change password |

All other protected API endpoints require:

```http
Authorization: Bearer <access_token>
```

### Flutter Integration

For the Android application:

- Store access and refresh tokens using `flutter_secure_storage`.
- Send the access token with protected API requests.
- If a request returns 401, attempt token refresh once.
- Retry the original request using the new access token.
- If refresh fails, return the owner to the login screen.

Never embed a permanent API key or JWT signing secret inside the Flutter application.

## API Endpoints

All endpoints are prefixed with `/api/v1`.

| Feature | Main endpoints |
|---|---|
| Dashboard | `GET /dashboard` |
| Daily journals | `/journals` |
| Purchases | `/purchases` |
| Hotel sales | `/hotel-sales` |
| Hotel accounts | `/accounts/hotels` |
| Hotel payments | `/hotel-payments` |
| Supplier accounts | `/accounts/suppliers` |
| Supplier payments | `/supplier-payments` |
| Fish management | `/fish` |
| Hotel management | `/hotels` |
| Supplier management | `/suppliers` |
| History | `GET /history` |
| Health check | `GET /health` |

See `openapi.json` for complete request and response schemas.

## Daily Journal Workflow

The normal business-day workflow is:

1. Create a journal for the business date.
2. Confirm opening stock for every active fish.
3. Record purchases during the day.
4. Record fish sold to hotels.
5. Record supplier payments separately when required.
6. Record hotel payments separately when received.
7. Enter actual remaining stock at closing.
8. Enter cash and UPI collection amounts.
9. Preview and close the journal.

The backend calculates normal-customer quantity from the stock movement.

Previous closing stock is suggested as the next journal's opening stock only when the latest earlier journal is closed.

## Important Business Rules

### Stock

- Every active fish requires confirmed opening stock.
- Zero is a valid quantity.
- Closing requires remaining stock for every active fish.
- Negative normal-customer quantity is rejected.
- Reopening a journal allows historical corrections before closing it again.

### Purchases and Suppliers

- Purchase amount is calculated from quantity multiplied by rate.
- Immediate payment is recorded against the supplier account.
- Unpaid purchase amounts create supplier outstanding balances.
- Later supplier payments are recorded independently from purchases.
- Payments cannot exceed the outstanding balance.
- Opening balances are separate ledger entries, not purchases.

### Hotel Sales and Payments

- Hotel sales increase hotel outstanding balances.
- Hotel payments are recorded independently from sales.
- Payments can be partial or full.
- Payments cannot exceed outstanding balances.
- Hotel opening balances are separate ledger entries, not sales.

### Daily Money

Cash and UPI collections are entered by the owner at journal closing.

Hotel payments, supplier payments, purchases, and daily cash/UPI collections remain separate records.

The application does not automatically reconcile these amounts.

### Historical Records

- Fish, hotels, and suppliers are deactivated rather than hard-deleted.
- Historical records are preserved.
- Editing or deleting transactions must respect historical running balances.
- A reopened journal hides its closing figures until it is closed again.

## Database Migrations

Database schema changes are managed through Alembic.

Apply migrations:

```bash
alembic upgrade head
```

Generate a migration after changing models:

```bash
alembic revision --autogenerate -m "describe change"
```

Review generated migrations before applying them.

The application does not automatically create database tables at startup.

## Project Structure

```text
fish-journal/
├── app/
│   ├── models.py
│   ├── schemas.py
│   ├── services.py
│   ├── security.py
│   ├── cli.py
│   ├── main.py
│   └── routers/
├── alembic/
│   └── versions/
├── tests/
├── .env.example
├── .gitignore
├── alembic.ini
├── openapi.json
├── requirements.txt
└── README.md
```

### Important Files

| File | Responsibility |
|---|---|
| `app/models.py` | Database models |
| `app/schemas.py` | Request and response validation |
| `app/services.py` | Business rules and operations |
| `app/security.py` | Authentication and token handling |
| `app/cli.py` | Owner account creation |
| `app/routers/` | HTTP API endpoints |
| `alembic/` | Database migrations |
| `tests/` | Automated tests |

## Android Emulator

The Android emulator can access the development machine using:

```text
http://10.0.2.2:8000/api/v1
```

For a physical Android device, use the development machine's local network IP address and ensure the server is accessible on the network.

## Deployment Guidelines

Before deploying:

- Configure a strong `JWT_SECRET`.
- Use PostgreSQL for a hosted production deployment.
- Serve the API over HTTPS.
- Keep `AUTH_DISABLED=false`.
- Keep `.env` and database credentials private.
- Disable Swagger documentation unless required.
- Use one worker unless login rate limiting is moved to shared storage.
- Run Alembic migrations before starting the application.

## Not Included

This backend intentionally does not implement:

- Profit or revenue calculations.
- Expense or wastage tracking.
- Cash reconciliation.
- Normal-customer profiles or individual bills.
- Multi-user or staff accounts.
- Combined hotel and supplier net positions.

The source of truth for application behavior is the Fish Business Daily Journal client requirements document.

---

**Project:** Fish Business Daily Journal  
**Platform:** Android  
**Backend:** FastAPI  
**Repository:** https://github.com/danishskh70/fish-journal