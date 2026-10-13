# Five-Minute Django Walkthrough

The assignment requires an unlisted video in your own voice, without slides. Record the following in the running Django project and add the real uploaded URL to `README.md`. No video has been recorded or uploaded yet.

## Script and Screen Checklist

1. **0:00–0:30 — Project and run contract**
   - Show root `manage.py`, root `requirements.txt`, and the source under `starter/core/`.
   - Show the PostgreSQL-only `DATABASE_URL` check in `starter/dealerdesk/settings.py`.

2. **0:30–1:10 — Schema and test state**
   - Show `Product.stock`, the order/order-item snapshot fields, unique idempotency key, and per-day sequence row.
   - Show the seeded 600 products and 25 dealers in PostgreSQL.

3. **1:10–2:00 — Order create and edit**
   - Call `POST /api/orders/` with two valid SKUs and quantities.
   - Point out DRAFT status, captured prices, line totals, subtotal, tax total, and grand total.
   - Call `PUT /api/orders/{order_number}/` with replacement items and show recalculated totals; mention it is DRAFT-only.

4. **2:00–3:25 — Confirm and lifecycle**
   - Show `starter/core/services.py` and the `select_for_update()` order/product locks.
   - Confirm the order and show the stock decrement.
   - Demonstrate insufficient stock returning `409 INSUFFICIENT_STOCK` without partial deductions.
   - Cancel a confirmed order and show stock restored once; demonstrate an invalid transition returning `409 INVALID_TRANSITION`.

5. **3:25–4:00 — Idempotency and daily numbers**
   - Submit the same `POST /api/orders/` twice with the same `Idempotency-Key`; show the replay returns the original order.
   - Reuse that key with a different body and show `409 IDEMPOTENCY_CONFLICT`.
   - Show two unique order numbers and the daily sequence row.

6. **4:00–4:40 — Supplier sync**
   - Show the mock running and its API settings, then call `POST /api/sync/supplier/`.
   - Point out pages/retries, rejected items, latest-timestamp duplicate selection, and that supplier stock does not overwrite local stock.

7. **4:40–5:00 — Verification and limitations**
   - Show `python manage.py check`, `python manage.py makemigrations --check --dry-run`, and `python manage.py test` results.
   - State honestly that assistant, forecasting, and frontend work are not implemented.

**Video URL:** pending recording and upload. Do not replace the placeholder with an invented link.