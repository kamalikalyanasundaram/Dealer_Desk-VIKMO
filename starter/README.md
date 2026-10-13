# DealerDesk Django Track

This extracted project is kept in `starter/`; the supplied `data/`, `smoke_test.py`, and `supplier_mock/` are siblings. For submission, copy the contents of `starter/` to the repository root beside those files: the grader requires root-level `manage.py` and `requirements.txt`. Do not commit `.env` or real credentials.

The Django track currently implements health, products, inventory, dealers, order create/list/retrieve, order status transitions and stock handling, idempotency, daily order numbers, and supplier catalogue sync. The contract-required `PUT /api/orders/{order_number}/` draft-item replacement endpoint remains unimplemented. AI/ML assistant, forecasting, and frontend features are not implemented.

The backend requires PostgreSQL; SQLite is rejected. `dealerdesk/settings.py` reads `DATABASE_URL` and fails clearly if it is missing or selects a non-PostgreSQL engine. Use a local PostgreSQL installation or a hosted PostgreSQL database. Docker is optional and is not used by the grader.

## Windows Setup

Open PowerShell at the extracted `VIKMO DealerDesk Assignment` folder and run:

```powershell
cd .\starter
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
```

Edit `.env` with a real PostgreSQL connection string and a locally generated `DJANGO_SECRET_KEY`. Never commit `.env` or share credential values. The environment variables are:

- `DATABASE_URL`: required PostgreSQL URL, e.g. `postgres://USER:PASSWORD@HOST:5432/dealerdesk`.
- `DJANGO_SECRET_KEY` and `DJANGO_DEBUG`: Django configuration.
- `SUPPLIER_API_URL` and `SUPPLIER_API_KEY`: required to run supplier sync; use the URL/key printed by the mock below.
- `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`: optional, for an assistant implementation only.

Install dependencies and initialize the schema:

```powershell
python -m pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --noinput
python manage.py seed_data
python manage.py seed_data
python manage.py showmigrations
python manage.py runserver 0.0.0.0:8000
```

To leave the virtual environment, run `deactivate`. The assignment requires Python 3.11 or newer; use a matching interpreter with `py -3.11`. Seeding twice is intentional and must not duplicate catalogue or dealer records.

## Implemented API Examples

```text
GET    /api/products/?search=brake&page_size=20
POST   /api/products/
# DealerDesk Django source

The Django project package and application remain in this folder. Run setup, management commands, tests, and the server from the repository root using the root `manage.py` and `requirements.txt`; see `../README.md` for instructions. The root launcher adds this folder to Python's import path and settings locate the sibling `data/` directory.
GET    /api/dealers/?page=1&page_size=20
