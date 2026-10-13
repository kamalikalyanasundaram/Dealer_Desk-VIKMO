from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import math
import time

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Product


PAGE_LIMIT = 20
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 10
SYNC_DEADLINE_SECONDS = 110
RETRY_BACKOFF_SECONDS = 0.5
SUPPLIER_FIELDS = (
    "name",
    "category",
    "brand",
    "vehicle_fitment",
    "description",
    "price",
)


class SupplierUnavailable(Exception):
    """The supplier feed could not be fetched or parsed completely."""


def _supplier_unavailable():
    return SupplierUnavailable("Could not fetch a complete supplier feed.")


def _retry_after(response):
    value = response.headers.get("Retry-After")
    try:
        delay = float(value)
    except (TypeError, ValueError):
        raise _supplier_unavailable() from None
    if not math.isfinite(delay) or delay < 0:
        raise _supplier_unavailable()
    return delay


def _sleep_before_retry(delay, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _supplier_unavailable()
    sleep_for = min(delay, remaining)
    time.sleep(sleep_for)
    if sleep_for < delay:
        raise _supplier_unavailable()


def _get_page(url, cursor, deadline):
    params = {"limit": PAGE_LIMIT}
    if cursor is not None:
        params["cursor"] = cursor
    headers = {"X-Api-Key": settings.SUPPLIER_API_KEY}
    requests_made = 0

    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _supplier_unavailable()
        requests_made += 1
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
            )
        except requests.RequestException:
            if attempt == MAX_ATTEMPTS - 1:
                raise _supplier_unavailable() from None
            _sleep_before_retry(RETRY_BACKOFF_SECONDS, deadline)
            continue

        if response.status_code == 429:
            if attempt == MAX_ATTEMPTS - 1:
                raise _supplier_unavailable()
            _sleep_before_retry(_retry_after(response), deadline)
            continue
        if 500 <= response.status_code < 600:
            if attempt == MAX_ATTEMPTS - 1:
                raise _supplier_unavailable()
            _sleep_before_retry(RETRY_BACKOFF_SECONDS, deadline)
            continue
        if response.status_code != 200:
            raise _supplier_unavailable()

        try:
            payload = response.json()
        except (ValueError, requests.RequestException):
            raise _supplier_unavailable() from None

        if not isinstance(payload, dict):
            raise _supplier_unavailable()
        items = payload.get("items")
        next_cursor = payload.get("next_cursor")
        if not isinstance(items, list):
            raise _supplier_unavailable()
        if next_cursor is not None and (
            not isinstance(next_cursor, str) or not next_cursor
        ):
            raise _supplier_unavailable()
        if any(not isinstance(item, dict) for item in items):
            raise _supplier_unavailable()
        return items, next_cursor, requests_made

    raise _supplier_unavailable()


def _parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_price(value):
    if not isinstance(value, str):
        return None
    try:
        price = Decimal(value)
    except InvalidOperation:
        return None
    if not price.is_finite() or price <= 0 or price.as_tuple().exponent < -2:
        return None
    return price


def _reject(item, reason):
    supplier_sku = item.get("supplier_sku")
    return {
        "supplier_sku": supplier_sku if isinstance(supplier_sku, str) else None,
        "reason": reason,
    }


def _validated_item(item):
    sku = item.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        return None, _reject(item, "missing or empty sku")
    sku = sku.strip()

    price = _parse_price(item.get("price"))
    if price is None:
        return None, _reject(item, "invalid price")

    updated_at = _parse_timestamp(item.get("updated_at"))
    if updated_at is None:
        return None, _reject(item, "invalid updated_at")

    fields = {}
    for field in SUPPLIER_FIELDS[:-1]:
        value = item.get(field)
        if not isinstance(value, str):
            return None, _reject(item, f"invalid {field}")
        if field != "description" and not value.strip():
            return None, _reject(item, f"invalid {field}")
        fields[field] = value
    fields["price"] = price

    candidate = Product(sku=sku, stock=0, **fields)
    try:
        candidate.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        field = next(iter(exc.message_dict), "product")
        return None, _reject(item, f"invalid {field}")

    return {"product": candidate, "updated_at": updated_at}, None


def _fetch_complete_feed():
    base_url = settings.SUPPLIER_API_URL.rstrip("/")
    if not base_url:
        raise _supplier_unavailable()
    url = f"{base_url}/v1/products"
    all_items = []
    pages_fetched = 0
    requests_made = 0
    cursor = None
    seen_cursors = set()
    deadline = time.monotonic() + SYNC_DEADLINE_SECONDS

    while True:
        if time.monotonic() >= deadline:
            raise _supplier_unavailable()
        if cursor is not None:
            if cursor in seen_cursors:
                raise _supplier_unavailable()
            seen_cursors.add(cursor)
        items, next_cursor, attempts = _get_page(url, cursor, deadline)
        requests_made += attempts
        pages_fetched += 1
        all_items.extend(items)
        cursor = next_cursor
        if cursor is None:
            return all_items, pages_fetched, requests_made


def _normalize_feed(items):
    rejected = []
    latest_by_sku = {}
    for item in items:
        normalized, rejection = _validated_item(item)
        if rejection:
            rejected.append(rejection)
            continue

        sku = normalized["product"].sku
        previous = latest_by_sku.get(sku)
        if previous is None or normalized["updated_at"] > previous["updated_at"]:
            latest_by_sku[sku] = normalized
    return latest_by_sku, rejected


@transaction.atomic
def _apply_feed(products_by_sku):
    current_products = {
        product.sku: product
        for product in Product.objects.select_for_update()
        .filter(sku__in=sorted(products_by_sku))
        .order_by("sku")
    }
    created = 0
    updated = 0
    unchanged = 0

    for sku, normalized in sorted(products_by_sku.items()):
        incoming = normalized["product"]
        current = current_products.get(sku)
        if current is None:
            Product.objects.create(
                sku=sku,
                name=incoming.name,
                category=incoming.category,
                brand=incoming.brand,
                vehicle_fitment=incoming.vehicle_fitment,
                description=incoming.description,
                price=incoming.price,
                stock=0,
            )
            created += 1
            continue

        changed_fields = []
        for field in SUPPLIER_FIELDS:
            value = getattr(incoming, field)
            if getattr(current, field) != value:
                setattr(current, field, value)
                changed_fields.append(field)
        if changed_fields:
            current.save(update_fields=changed_fields)
            updated += 1
        else:
            unchanged += 1

    return created, updated, unchanged


def sync_supplier_catalogue():
    items, pages_fetched, requests_made = _fetch_complete_feed()
    products_by_sku, rejected = _normalize_feed(items)
    created, updated, unchanged = _apply_feed(products_by_sku)
    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "rejected": rejected,
        "pages_fetched": pages_fetched,
        "requests_made": requests_made,
    }