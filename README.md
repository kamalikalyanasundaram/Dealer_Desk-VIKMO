# VIKMO DealerDesk — Django Track

**Public GitHub repository:** _Not published yet._

The project is packaged for the grader with `manage.py`, `requirements.txt`, this README, and `.env.example` at the repository root. The Django source remains in `starter/`; the root launcher adds that directory to Python's path and preserves the original extracted tree. The supplied `data/`, `API_CONTRACT.md`, PDF, smoke test, and supplier mock remain in their original locations.

## Implemented Scope

Implemented: health, Products, Inventory, Dealers, order create/list/retrieve, DRAFT order-item replacement, status transitions and stock reservation/cancellation, order idempotency and daily order numbering, and supplier synchronization. Optional assistant, forecasting, and frontend parts are not implemented.

## Windows Setup

Requirements: Python 3.11+ and PostgreSQL. SQLite is unsupported. Docker is optional; the grader does not use it.

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
python -m pip install -r requirements.txt
```

Edit the ignored local `.env` with a real PostgreSQL `DATABASE_URL` and a generated `DJANGO_SECRET_KEY`. Never commit or share `.env` values. The application reads:

- `DATABASE_URL` (required; PostgreSQL URL)
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`
- `SUPPLIER_API_URL`, `SUPPLIER_API_KEY` (supplier integration)
- `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY` (only if implementing an assistant)

Initialize and check the database:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py seed_data
python manage.py seed_data
python manage.py showmigrations
python manage.py test
python manage.py runserver 0.0.0.0:8000 --noreload
```

The second seed run is intentional; it must preserve existing product stock and create no duplicates.

## API Examples

All paths end with `/`; response fields and error codes are specified in `API_CONTRACT.md`.

```http
GET /api/products/?search=brake&page_size=20
POST /api/products/
Content-Type: application/json

{"sku":"ACC-1001","name":"Universal Mount","category":"Universal Accessories","brand":"Moto Torque","vehicle_fitment":"Universal","price":"875.25","description":"Mount"}
```

```http
PUT /api/inventory/ACC-1001/
Content-Type: application/json

{"quantity":25,"reason":"stock count correction"}
```

```http
POST /api/orders/
Content-Type: application/json
Idempotency-Key: client-request-001

{"dealer_id":7,"items":[{"sku":"ACC-1001","quantity":2}]}
```

```http
PUT /api/orders/ORD-20261012-0001/
Content-Type: application/json

{"items":[{"sku":"ACC-1001","quantity":3}]}
```

Also available: product retrieve/PATCH; dealer list/create/retrieve; order list/detail/edit and `confirm`, `dispatch`, `deliver`, `cancel`; and `POST /api/sync/supplier/`.

## Supplier Mock

From the repository root, start the mock in a separate PowerShell terminal:

```powershell
python supplier_mock/mock_supplier.py
```

Use its printed `SUPPLIER_API_URL` and `SUPPLIER_API_KEY` in `.env`, then restart Django. The default mock exercises throttling and a temporary failure. `--calm` disables those behaviors; `--outage` simulates a page that never recovers. Supplier stock is never copied to local inventory.

## Smoke Test

Run only against a disposable, freshly migrated and seeded PostgreSQL database, with Django and the supplier mock running:

```powershell
python smoke_test.py --base-url http://localhost:8000 --track django
```

It creates a dealer and order, changes inventory, confirms/cancels the order, and runs supplier sync. It therefore modifies its target database. Passing the smoke test does not replace the business-rule and concurrency tests.

## Decisions and Walkthrough

See `DECISIONS.md` for implementation decisions and known limitations. A five-minute walkthrough script is in `WALKTHROUGH.md`. No video URL has been supplied or uploaded yet; add the actual unlisted YouTube, Loom, or Drive URL here after recording:

**Video walkthrough:** _Pending recording and upload._