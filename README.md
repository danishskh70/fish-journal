# Fish Business Daily Journal — Backend

FastAPI + SQLAlchemy 2 + Pydantic v2. SQLite by default, Postgres via `DATABASE_URL`.
Single owner, no user accounts. Source of truth: the client requirements document.
`openapi.json` is included for Flutter client generation. Live docs at `/docs`.

## Run (Windows CMD)

```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: set `JWT_SECRET` (32+ random chars). Generate one:

```cmd
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

Load `.env` into the shell (CMD has no auto-load), then migrate, create owner, run:

```cmd
set JWT_SECRET=<paste secret>
alembic upgrade head
python -m app.cli create-owner --username owner
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

PowerShell: use `$env:JWT_SECRET="..."` instead of `set`.
Local dev without login: `set AUTH_DISABLED=true`. Server refuses to start with no strong `JWT_SECRET` unless this is set.
Swagger UI: `set ENABLE_DOCS=true`, open `/docs`.

Tests:

```cmd
python -m pytest -q
```

Android emulator reaches PC at `http://10.0.2.2:8000/api/v1`.

## Authentication

Single owner login. Passwords: scrypt. Access token: JWT, 15 min. Refresh token: 30 days, stored server-side, rotated on every use. Reusing an old refresh token revokes all sessions. Password change logs out everywhere. Login locks 15 min after 5 failures (per IP + username, per process).

| Endpoint | Use |
|---|---|
| `POST /api/v1/auth/login` `{username,password}` | returns `access_token`, `refresh_token`, `expires_in` |
| `POST /api/v1/auth/refresh` `{refresh_token}` | new pair, old refresh dead |
| `POST /api/v1/auth/logout` `{refresh_token}` | revoke |
| `POST /api/v1/auth/change-password` | needs bearer token |
| `GET /api/v1/auth/me` | check session |

All other `/api/v1` endpoints need `Authorization: Bearer <access_token>`. Flutter: keep tokens in `flutter_secure_storage`; on 401 call refresh once, retry, else show login.

**Deploy rules:** serve only over HTTPS (Render and most hosts do this). Run one worker, or move the login limiter to shared storage first. Rotate `JWT_SECRET` to log everyone out.

## Migrations (Alembic)

Startup no longer creates tables. Schema changes go through Alembic:

```cmd
alembic upgrade head
alembic revision --autogenerate -m "describe change"
```

A test checks migrations match the models.

## Layout

| Path | What |
|---|---|
| `app/models.py` | 11 documented tables (fish, supplier, hotel, hotel_rate, journal, opening_stock, purchase, supplier_payment, hotel_sale, hotel_payment, closing_stock) + hotel_opening_balance, supplier_opening_balance, owner_account, refresh_token |
| `app/security.py`, `app/cli.py` | Auth, owner creation |
| `alembic/` | Migrations |
| `app/services.py` | All business rules |
| `app/routers/` | Thin HTTP layer, prefix `/api/v1` |
| `tests/` | One test per important rule |

## API (prefix `/api/v1`)

| Screen | Endpoints |
|---|---|
| Dashboard | `GET /dashboard?business_date=` |
| Daily Journal | `POST /journals`, `GET /journals/{id}`, `GET /journals/by-date/{date}`, `PUT /journals/{id}/opening-stock`, `POST /journals/{id}/close-preview`, `POST /journals/{id}/close`, `POST /journals/{id}/reopen` |
| Purchases | `POST/GET /purchases`, `GET/PUT/DELETE /purchases/{id}` |
| Hotel Sales | `POST/GET /hotel-sales`, `GET/PUT/DELETE /hotel-sales/{id}` |
| Hotel Accounts | `GET /accounts/hotels`, `/accounts/hotels/{id}/ledger`, `/accounts/hotels/{id}/monthly-summary?year&month`, `/accounts/hotels/monthly-summary?year&month` |
| Hotel Payments | `POST/GET /hotel-payments`, `PUT/DELETE /hotel-payments/{id}` |
| Supplier Accounts | `GET /accounts/suppliers`, `/accounts/suppliers/{id}/ledger` |
| Supplier Payments | `POST/GET /supplier-payments`, `PUT/DELETE /supplier-payments/{id}` (later payments only) |
| Fish / Hotel / Supplier Mgmt | `/fish`, `/hotels` (+ `/hotels/{id}/rates/{fish_id}`), `/suppliers` — create, list, get, PATCH (deactivate instead of delete) |
| Opening balances | `GET/PUT /hotels/{id}/opening-balance`, `GET/PUT /suppliers/{id}/opening-balance` `{amount, balance_date}`; or `opening_balance` + `opening_balance_date` when registering |
| History | `GET /history?from_date&to_date&limit&offset` |

Ledger endpoints accept `from_date` / `to_date`; response has `previous_balance`, entries with `running_balance`, `closing_balance`.
All numbers are JSON numbers. Dates are `YYYY-MM-DD`.

### Daily flow for Flutter

1. `POST /journals` `{ "business_date": "2026-11-24" }` → rows carry `suggested_opening`.
2. `PUT /journals/{id}/opening-stock` — send `quantity`, or omit `quantity` to accept suggestion.
3. `POST /purchases`, `POST /hotel-sales` during day.
4. `POST /journals/{id}/close-preview` (optional) then `POST /journals/{id}/close` with remaining per fish + `cash_amount` + `upi_amount`.
5. Errors on close: `422` with `detail` = list of problems. Reopen without confirm: `409` with `detail.warning`.

## Rules added by owner decision

- Negative normal-customer quantity: close rejected, 422.
- `paid_now` above purchase amount: rejected.
- **Payments never exceed outstanding balance.** Supplier and hotel payments rejected with 422 if above balance as of payment date. No advance payments. Any edit or delete that would push a running balance below zero on any date is rejected too (e.g. deleting a sale already paid).
- **Opening balances** are their own ledger entry (`entry_type: opening_balance`), never a sale or purchase. Default zero. Counted in ledgers, balances as-of date, dashboard totals, journal history. In monthly summary an opening balance dated inside the month is brought forward as that month's opening outstanding, not as fish taken. Setting amount 0 removes the entry.
- **Stock suggestion** uses only the latest earlier journal, and only if closed. If that journal is open, suggestion is `null`. Older journals never used. Manual opening stock always possible.
- Fish, hotels, suppliers: deactivate, never delete.

## Other interpretations (flag if wrong)

1. Journal stock covers every active fish. All need confirmed opening and remaining quantity to close.
2. Reopened journal hides money and remaining figures until closed again.
3. Immediate supplier payment is dated the journal date and edited only through its purchase.
4. "Previous day" = latest earlier journal by date (shop-closed days skipped).

Not built (section 15): profit, revenue, expenses, wastage, cash reconciliation, customer profiles, multi-user, net position.
