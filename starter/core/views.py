import hashlib
import json

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from .models import Dealer, Order, OrderItem, Product
from .serializers import (
    DealerSerializer,
    InventoryUpdateSerializer,
    OrderCreateSerializer,
    OrderItemsReplacementSerializer,
    OrderReadSerializer,
    ProductCreateSerializer,
    ProductPatchSerializer,
    ProductSerializer,
    calculate_order_lines,
)
from .services import create_order_with_idempotency, transition_order
from .supplier_sync import SupplierUnavailable, sync_supplier_catalogue


def health(request):
    """GET /api/health/ — the grader polls this until your app is ready."""
    return JsonResponse({"status": "ok"})


class ProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ProductListCreateView(generics.ListCreateAPIView):
    pagination_class = ProductPagination
    queryset = Product.objects.all()
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return ProductCreateSerializer
        return ProductSerializer

    def get_queryset(self):
        products = Product.objects.order_by("sku")
        search = self.request.query_params.get("search")
        category = self.request.query_params.get("category")
        vehicle = self.request.query_params.get("vehicle")

        if search:
            products = products.filter(
                Q(sku__icontains=search)
                | Q(name__icontains=search)
                | Q(brand__icontains=search)
            )
        if category is not None:
            products = products.filter(category=category)
        if vehicle:
            products = products.filter(vehicle_fitment__icontains=vehicle)
        return products

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sku = serializer.validated_data["sku"]
        if Product.objects.filter(sku=sku).exists():
            return self._duplicate_sku_response()

        try:
            with transaction.atomic():
                product = serializer.save(stock=0)
        except IntegrityError:
            if Product.objects.filter(sku=sku).exists():
                return self._duplicate_sku_response()
            raise

        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _duplicate_sku_response():
        return Response(
            {
                "error": {
                    "code": "DUPLICATE",
                    "message": "A product with this SKU already exists.",
                    "details": [],
                }
            },
            status=status.HTTP_409_CONFLICT,
        )


class ProductDetailView(generics.RetrieveUpdateAPIView):
    queryset = Product.objects.all()
    lookup_field = "sku"
    lookup_url_kwarg = "sku"
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return ProductPatchSerializer
        return ProductSerializer

    def patch(self, request, *args, **kwargs):
        if "sku" in request.data:
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "SKU cannot be changed.",
                        "details": [{"field": "sku", "message": "This field is read-only."}],
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(ProductSerializer(product).data, status=status.HTTP_200_OK)


class InventoryUpdateView(APIView):
    http_method_names = ["put", "options"]

    def put(self, request, sku):
        serializer = InventoryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = get_object_or_404(Product, sku=sku)
        quantity = serializer.validated_data["quantity"]
        product.stock = quantity
        product.save(update_fields=["stock"])

        return Response(
            {"sku": product.sku, "quantity": product.stock},
            status=status.HTTP_200_OK,
        )


class DealerListCreateView(generics.ListCreateAPIView):
    serializer_class = DealerSerializer
    pagination_class = ProductPagination
    queryset = Dealer.objects.all()
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return Dealer.objects.order_by("id")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dealer_code = serializer.validated_data["dealer_code"]
        if Dealer.objects.filter(dealer_code=dealer_code).exists():
            return self._duplicate_code_response()

        try:
            with transaction.atomic():
                dealer = serializer.save()
        except IntegrityError:
            if Dealer.objects.filter(dealer_code=dealer_code).exists():
                return self._duplicate_code_response()
            raise

        return Response(
            DealerSerializer(dealer).data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _duplicate_code_response():
        return Response(
            {
                "error": {
                    "code": "DUPLICATE",
                    "message": "A dealer with this dealer code already exists.",
                    "details": [],
                }
            },
            status=status.HTTP_409_CONFLICT,
        )


class DealerDetailView(generics.RetrieveAPIView):
    serializer_class = DealerSerializer
    queryset = Dealer.objects.all()
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        return Dealer.objects.order_by("id")


class OrderListCreateView(generics.ListCreateAPIView):
    pagination_class = ProductPagination
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return OrderCreateSerializer
        return OrderReadSerializer

    def get_queryset(self):
        orders = Order.objects.select_related("dealer").prefetch_related(
            "items__product"
        )
        dealer_id = self.request.query_params.get("dealer_id")
        status_filter = self.request.query_params.get("status")

        if dealer_id is not None:
            if not dealer_id.isascii() or not dealer_id.isdigit() or int(dealer_id) < 1:
                raise ValidationError({"dealer_id": "Must be a positive integer."})
            orders = orders.filter(dealer_id=int(dealer_id))
        if status_filter is not None:
            if status_filter not in Order.Status.values:
                raise ValidationError({"status": "Invalid order status."})
            orders = orders.filter(status=status_filter)

        return orders.order_by("-created_at", "order_number")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        idempotency_key = request.headers.get("Idempotency-Key")
        if idempotency_key is not None and (
            not idempotency_key or len(idempotency_key) > 255
        ):
            raise ValidationError(
                {"Idempotency-Key": "Must be a non-empty value of at most 255 characters."}
            )

        fingerprint_payload = {
            "dealer_id": serializer.validated_data["dealer_id"].pk,
            "items": [
                {"sku": item["sku"].sku, "quantity": item["quantity"]}
                for item in serializer.validated_data["items"]
            ],
        }
        request_hash = hashlib.sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        order, request_matches, created = create_order_with_idempotency(
            serializer,
            idempotency_key,
            request_hash,
        )
        if not request_matches:
            return Response(
                {
                    "error": {
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "Idempotency-Key was already used with a different request body.",
                        "details": [],
                    }
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            OrderReadSerializer(order).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class OrderDetailView(generics.RetrieveAPIView):
    serializer_class = OrderReadSerializer
    lookup_field = "order_number"
    lookup_url_kwarg = "order_number"
    http_method_names = ["get", "put", "head", "options"]

    def get_queryset(self):
        return Order.objects.select_related("dealer").prefetch_related(
            "items__product"
        )

    def put(self, request, order_number):
        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(), order_number=order_number
            )
            if order.status != Order.Status.DRAFT:
                return Response(
                    {
                        "error": {
                            "code": "ORDER_LOCKED",
                            "message": "Only DRAFT orders can be edited.",
                            "details": [],
                        }
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            serializer = OrderItemsReplacementSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            line_data, subtotal, tax_total = calculate_order_lines(
                serializer.validated_data["items"]
            )
            OrderItem.objects.filter(order=order).delete()
            OrderItem.objects.bulk_create(
                [OrderItem(order=order, **item) for item in line_data]
            )
            order.subtotal = subtotal
            order.tax_total = tax_total
            order.grand_total = subtotal + tax_total
            order.save(
                update_fields=["subtotal", "tax_total", "grand_total", "updated_at"]
            )

        return Response(OrderReadSerializer(order).data, status=status.HTTP_200_OK)


class OrderTransitionView(APIView):
    http_method_names = ["post", "options"]
    action = None

    def post(self, request, order_number):
        order, failure = transition_order(order_number, self.action)
        if failure:
            return Response(
                {
                    "error": {
                        "code": failure["code"],
                        "message": failure["message"],
                        "details": failure["details"],
                    }
                },
                status=failure["status"],
            )
        return Response(OrderReadSerializer(order).data, status=status.HTTP_200_OK)


class SupplierSyncView(APIView):
    http_method_names = ["post", "options"]

    def post(self, request):
        try:
            result = sync_supplier_catalogue()
        except SupplierUnavailable:
            return Response(
                {
                    "error": {
                        "code": "SUPPLIER_UNAVAILABLE",
                        "message": "Could not fetch a complete supplier feed.",
                        "details": [],
                    }
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(result, status=status.HTTP_200_OK)
