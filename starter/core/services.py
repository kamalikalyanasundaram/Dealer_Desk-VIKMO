from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import DailyOrderNumberSequence, IdempotencyRecord, Order, OrderItem, Product


TRANSITIONS = {
    "confirm": (Order.Status.DRAFT, Order.Status.CONFIRMED),
    "dispatch": (Order.Status.CONFIRMED, Order.Status.DISPATCHED),
    "deliver": (Order.Status.DISPATCHED, Order.Status.DELIVERED),
}


class ConcurrentIdempotencyClaim(Exception):
    pass


def allocate_order_number():
    today = timezone.localdate()
    sequence, _ = DailyOrderNumberSequence.objects.get_or_create(
        sequence_date=today,
        defaults={"last_sequence": 0},
    )
    sequence = DailyOrderNumberSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_sequence += 1
    sequence.save(update_fields=["last_sequence"])
    return f"ORD-{today:%Y%m%d}-{sequence.last_sequence:04d}"


def create_order_with_idempotency(serializer, key, request_hash):
    try:
        with transaction.atomic():
            if key:
                existing = (
                    IdempotencyRecord.objects.select_for_update()
                    .select_related("order")
                    .filter(key=key)
                    .first()
                )
                if existing:
                    return existing.order, existing.request_hash == request_hash, False

            order = serializer.save()
            if key:
                try:
                    with transaction.atomic():
                        IdempotencyRecord.objects.create(
                            key=key,
                            request_hash=request_hash,
                            order=order,
                        )
                except IntegrityError as exc:
                    raise ConcurrentIdempotencyClaim from exc
            return order, True, True
    except ConcurrentIdempotencyClaim:
        record = IdempotencyRecord.objects.select_related("order").get(key=key)
        return record.order, record.request_hash == request_hash, False


def _failure(code, message, status_code, details=None):
    return {
        "code": code,
        "message": message,
        "details": details or [],
        "status": status_code,
    }


def _locked_order_items(order):
    items = list(
        OrderItem.objects.filter(order=order)
        .select_related("product")
        .order_by("product_id")
    )
    product_ids = sorted({item.product_id for item in items})
    products = Product.objects.select_for_update().filter(pk__in=product_ids).order_by("pk")
    return items, {product.pk: product for product in products}


@transaction.atomic
def transition_order(order_number, action):
    try:
        order = Order.objects.select_for_update().get(order_number=order_number)
    except Order.DoesNotExist:
        return None, _failure("NOT_FOUND", "Order not found.", 404)

    if action == "cancel":
        if order.status not in (Order.Status.DRAFT, Order.Status.CONFIRMED):
            return None, _failure(
                "INVALID_TRANSITION",
                f"Cannot cancel an order with status {order.status}.",
                409,
            )
        if order.status == Order.Status.CONFIRMED:
            items, products = _locked_order_items(order)
            for item in items:
                products[item.product_id].stock += item.quantity
            for product in products.values():
                product.save(update_fields=["stock"])
        order.status = Order.Status.CANCELLED
    else:
        expected_status, new_status = TRANSITIONS[action]
        if order.status != expected_status:
            return None, _failure(
                "INVALID_TRANSITION",
                f"Cannot {action} an order with status {order.status}.",
                409,
            )

        if action == "confirm":
            items, products = _locked_order_items(order)
            short_lines = [
                (item, products[item.product_id])
                for item in items
                if products[item.product_id].stock < item.quantity
            ]
            if short_lines:
                details = [
                    {
                        "sku": product.sku,
                        "requested": item.quantity,
                        "available": product.stock,
                    }
                    for item, product in short_lines
                ]
                messages = [
                    f"Insufficient stock for {item.name}. Available: {product.stock}, "
                    f"Requested: {item.quantity}"
                    for item, product in short_lines
                ]
                return None, _failure(
                    "INSUFFICIENT_STOCK",
                    ". ".join(messages),
                    409,
                    details,
                )

            for item in items:
                products[item.product_id].stock -= item.quantity
            for product in products.values():
                product.save(update_fields=["stock"])

        order.status = new_status

    order.save(update_fields=["status", "updated_at"])
    return order, None