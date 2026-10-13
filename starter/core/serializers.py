from decimal import Decimal, ROUND_HALF_UP
import re

from django.db import transaction
from rest_framework import serializers

from .models import (
    Dealer,
    Order,
    OrderItem,
    Product,
)
from .services import allocate_order_number


class StrictInputMixin:
    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown_fields = set(data.keys()) - set(self.fields)
            if unknown_fields:
                raise serializers.ValidationError(
                    {field: "This field is not allowed." for field in sorted(unknown_fields)}
                )
        return super().to_internal_value(data)


class StrictIntegerField(serializers.IntegerField):
    default_error_messages = {"invalid": "A whole number is required."}

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, int):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictCharField(serializers.CharField):
    default_error_messages = {"invalid": "A text value is required."}

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class MoneyDecimalField(serializers.DecimalField):
    default_error_messages = {"invalid": "A money string with two decimal places is required."}

    def to_internal_value(self, data):
        if not isinstance(data, str) or not re.fullmatch(r"-?\d+\.\d{2}", data):
            self.fail("invalid")
        return super().to_internal_value(data)


class InventoryUpdateSerializer(StrictInputMixin, serializers.Serializer):
    quantity = StrictIntegerField(min_value=0)
    reason = StrictCharField(allow_blank=False, trim_whitespace=True)


class DealerSerializer(StrictInputMixin, serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    dealer_code = StrictCharField(max_length=64, validators=[])
    name = StrictCharField(max_length=255)
    city = StrictCharField(max_length=100, required=False, allow_blank=True, default="")
    phone = StrictCharField(max_length=32, required=False, allow_blank=True, default="")
    email = serializers.EmailField(
        max_length=254, required=False, allow_blank=True, default=""
    )
    gstin = StrictCharField(max_length=32, required=False, allow_blank=True, default="")
    credit_limit = MoneyDecimalField(
        max_digits=12,
        decimal_places=2,
        coerce_to_string=True,
        required=False,
        default=Decimal("0.00"),
    )

    class Meta:
        model = Dealer
        fields = (
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        )


class OrderItemInputSerializer(StrictInputMixin, serializers.Serializer):
    sku = serializers.SlugRelatedField(
        slug_field="sku", queryset=Product.objects.all()
    )
    quantity = StrictIntegerField(min_value=1, max_value=2147483647)

    def to_internal_value(self, data):
        if isinstance(data, dict) and "sku" in data and not isinstance(data["sku"], str):
            raise serializers.ValidationError({"sku": "A SKU string is required."})
        return super().to_internal_value(data)


def validate_order_items(items):
    skus = [item["sku"].sku for item in items]
    if len(skus) != len(set(skus)):
        raise serializers.ValidationError("A SKU may appear only once per order.")

    maximum_amount = Decimal("999999999999.99")
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    for item in items:
        line_subtotal = item["sku"].price * item["quantity"]
        line_tax = (line_subtotal * Decimal("0.18")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if line_subtotal + line_tax > maximum_amount:
            raise serializers.ValidationError(
                "An order line total exceeds the supported monetary range."
            )
        subtotal += line_subtotal
        tax_total += line_tax
    if subtotal + tax_total > maximum_amount:
        raise serializers.ValidationError(
            "The order total exceeds the supported monetary range."
        )
    return items


def calculate_order_lines(items):
    line_data = []
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")
    for item in items:
        product = item["sku"]
        quantity = item["quantity"]
        line_subtotal = product.price * quantity
        line_tax = (line_subtotal * Decimal("0.18")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        line_total = line_subtotal + line_tax
        line_data.append(
            {
                "product": product,
                "name": product.name,
                "quantity": quantity,
                "unit_price": product.price,
                "line_subtotal": line_subtotal,
                "line_tax": line_tax,
                "line_total": line_total,
            }
        )
        subtotal += line_subtotal
        tax_total += line_tax
    return line_data, subtotal, tax_total


class OrderCreateSerializer(StrictInputMixin, serializers.Serializer):
    dealer_id = StrictIntegerField(min_value=1)
    items = OrderItemInputSerializer(many=True, allow_empty=False)

    def validate_dealer_id(self, dealer_id):
        try:
            return Dealer.objects.get(pk=dealer_id)
        except Dealer.DoesNotExist:
            raise serializers.ValidationError("Unknown dealer.") from None

    def validate_items(self, items):
        return validate_order_items(items)

    @transaction.atomic
    def create(self, validated_data):
        order_number = allocate_order_number()

        line_data, subtotal, tax_total = calculate_order_lines(validated_data["items"])

        order = Order.objects.create(
            order_number=order_number,
            dealer=validated_data["dealer_id"],
            status=Order.Status.DRAFT,
            subtotal=subtotal,
            tax_total=tax_total,
            grand_total=subtotal + tax_total,
        )
        OrderItem.objects.bulk_create(
            [OrderItem(order=order, **item) for item in line_data]
        )
        return order


class OrderItemsReplacementSerializer(StrictInputMixin, serializers.Serializer):
    items = OrderItemInputSerializer(many=True, allow_empty=False)

    def validate_items(self, items):
        return validate_order_items(items)


class OrderItemReadSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="product.sku", read_only=True)
    unit_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True, read_only=True
    )
    line_subtotal = serializers.DecimalField(
        max_digits=14, decimal_places=2, coerce_to_string=True, read_only=True
    )
    line_tax = serializers.DecimalField(
        max_digits=14, decimal_places=2, coerce_to_string=True, read_only=True
    )
    line_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, coerce_to_string=True, read_only=True
    )

    class Meta:
        model = OrderItem
        fields = (
            "sku",
            "name",
            "quantity",
            "unit_price",
            "line_subtotal",
            "line_tax",
            "line_total",
        )


class OrderReadSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(read_only=True)
    items = OrderItemReadSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(
        max_digits=14, decimal_places=2, coerce_to_string=True, read_only=True
    )
    tax_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, coerce_to_string=True, read_only=True
    )
    grand_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, coerce_to_string=True, read_only=True
    )

    class Meta:
        model = Order
        fields = (
            "order_number",
            "dealer_id",
            "status",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        )


class StrictProductSerializer(StrictInputMixin, serializers.ModelSerializer):
    pass


class ProductSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True, read_only=True
    )

    class Meta:
        model = Product
        fields = (
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "stock",
            "description",
            "image_url",
            "model_3d_url",
        )
        read_only_fields = fields


class ProductCreateSerializer(StrictProductSerializer):
    sku = serializers.CharField(max_length=64, validators=[])
    price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        coerce_to_string=True,
    )
    description = serializers.CharField(allow_blank=True, required=True)

    class Meta:
        model = Product
        fields = (
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
            "image_url",
            "model_3d_url",
        )


class ProductPatchSerializer(StrictProductSerializer):
    price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        coerce_to_string=True,
        required=False,
    )

    class Meta:
        model = Product
        fields = (
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
            "image_url",
            "model_3d_url",
        )