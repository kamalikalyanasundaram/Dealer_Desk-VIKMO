from django.db import models
from django.db.models import Q


class Product(models.Model):
    sku = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, db_index=True)
    brand = models.CharField(max_length=100, db_index=True)
    vehicle_fitment = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(price__gt=0), name="product_price_positive"),
            models.CheckConstraint(check=Q(stock__gte=0), name="product_stock_nonnegative"),
        ]

    def __str__(self):
        return f"{self.sku} - {self.name}"

    image_url = models.URLField(blank=True, default="")
    model_3d_url = models.URLField(blank=True, default="")


class Dealer(models.Model):
    dealer_code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=32, blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.dealer_code} - {self.name}"


class Order(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"

    order_number = models.CharField(max_length=32, unique=True)
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["dealer", "status"], name="order_dealer_status_idx")]

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    line_tax = models.DecimalField(max_digits=14, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "product"], name="order_item_product_unique"),
            models.CheckConstraint(check=Q(quantity__gte=1), name="order_item_quantity_positive"),
        ]


class IdempotencyRecord(models.Model):
    key = models.CharField(max_length=255, unique=True)
    request_hash = models.CharField(max_length=64)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="idempotency_records")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["created_at"], name="idempotency_created_idx")]


class DailyOrderNumberSequence(models.Model):
    sequence_date = models.DateField(unique=True)
    last_sequence = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(last_sequence__gte=0), name="order_sequence_nonnegative"),
        ]