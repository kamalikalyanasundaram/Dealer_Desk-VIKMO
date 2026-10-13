import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, call, patch

import requests
from django import db
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from core.models import (
    DailyOrderNumberSequence,
    Dealer,
    IdempotencyRecord,
    Order,
    OrderItem,
    Product,
)


CATALOGUE_HEADERS = [
    "sku",
    "name",
    "category",
    "brand",
    "vehicle_fitment",
    "price",
    "stock",
    "description",
]
DEALER_HEADERS = ["dealer_code", "name", "city", "phone", "email", "gstin", "credit_limit"]


class SeedDataCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self._write_csv(
            "catalogue.csv",
            CATALOGUE_HEADERS,
            [["TST-001", "Test Part", "Brakes", "Test Brand", "Universal", "12.35", "7", ""]],
        )
        self._write_csv(
            "dealers.csv",
            DEALER_HEADERS,
            [["TST-001", "Test Dealer", "", "", "", "", "100.25"]],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_csv(self, filename, headers, rows):
        with (self.data_dir / filename).open("w", encoding="utf-8", newline="") as target:
            writer = csv.writer(target)
            writer.writerow(headers)
            writer.writerows(rows)

    def test_repeated_seed_preserves_existing_inventory(self):
        call_command("seed_data", data_dir=self.data_dir)
        product = Product.objects.get(sku="TST-001")
        self.assertEqual(product.price.as_tuple().exponent, -2)
        self.assertEqual(product.stock, 7)

        product.stock = 3
        product.save(update_fields=["stock"])
        call_command("seed_data", data_dir=self.data_dir)

        self.assertEqual(Product.objects.filter(sku="TST-001").count(), 1)
        self.assertEqual(Dealer.objects.filter(dealer_code="TST-001").count(), 1)
        self.assertEqual(Product.objects.get(sku="TST-001").stock, 3)

    def test_invalid_catalogue_row_reports_line_and_writes_nothing(self):
        self._write_csv(
            "catalogue.csv",
            CATALOGUE_HEADERS,
            [["TST-001", "Test Part", "Brakes", "Test Brand", "Universal", "N/A", "7", ""]],
        )

        with self.assertRaises(CommandError) as raised:
            call_command("seed_data", data_dir=self.data_dir)

        self.assertIn("catalogue.csv:2", str(raised.exception))
        self.assertIn("price", str(raised.exception))
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(Dealer.objects.count(), 0)

    def test_missing_dealer_file_reports_error_without_partial_import(self):
        (self.data_dir / "dealers.csv").unlink()

        with self.assertRaises(CommandError) as raised:
            call_command("seed_data", data_dir=self.data_dir)

        self.assertIn("dealers.csv", str(raised.exception))
        self.assertEqual(Product.objects.count(), 0)
        self.assertEqual(Dealer.objects.count(), 0)


class ProductsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product = Product.objects.create(
            sku="BRK-TEST-01",
            name="Brake Pad Set",
            category="Brakes",
            brand="Endurance",
            vehicle_fitment="Bajaj Pulsar 150",
            price="1459.50",
            stock=12,
            description="Replacement pads",
        )
        Product.objects.create(
            sku="BRK-TEST-02",
            name="Brake Disc",
            category="Brakes",
            brand="RoadCraft",
            vehicle_fitment="Bajaj Pulsar 220",
            price="2099.00",
            stock=5,
            description="Front disc",
        )
        Product.objects.create(
            sku="OIL-TEST-01",
            name="Engine Oil",
            category="Engine & Oils",
            brand="Endurance",
            vehicle_fitment="Universal",
            price="650.00",
            stock=8,
            description="Synthetic oil",
        )

    def _assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"].get("message"), str)
        self.assertIsInstance(body["error"].get("details"), list)

    def _new_product_payload(self, **overrides):
        payload = {
            "sku": "ACC-NEW-01",
            "name": "Universal Phone Mount",
            "category": "Universal Accessories",
            "brand": "Moto Torque",
            "vehicle_fitment": "Universal",
            "price": "875.25",
            "description": "Handlebar phone mount",
        }
        payload.update(overrides)
        return payload

    def test_list_response_fields_and_pagination(self):
        for number in range(22):
            Product.objects.create(
                sku=f"ZZ-TEST-{number:02d}",
                name=f"Test Product {number:02d}",
                category="Test",
                brand="Test Brand",
                vehicle_fitment="Universal",
                price="1.00",
                stock=0,
                description="",
            )

        response = self.client.get("/api/products/?page_size=5&page=2")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"count", "next", "previous", "results"})
        self.assertEqual(body["count"], 25)
        self.assertIsNotNone(body["next"])
        self.assertIsNotNone(body["previous"])
        self.assertEqual(len(body["results"]), 5)
        self.assertEqual(
            set(body["results"][0]),
            {
                "sku",
                "name",
                "category",
                "brand",
                "vehicle_fitment",
                "price",
                "stock",
                "description",
            },
        )
        self.assertIsInstance(body["results"][0]["price"], str)
        self.assertEqual(body["results"][0]["price"].count("."), 1)

    def test_search_matches_sku_name_and_brand_case_insensitively(self):
        for query, expected in (
            ("brk-test-01", ["BRK-TEST-01"]),
            ("PAD SET", ["BRK-TEST-01"]),
            ("endURANCE", ["BRK-TEST-01", "OIL-TEST-01"]),
        ):
            with self.subTest(query=query):
                response = self.client.get("/api/products/", {"search": query})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [item["sku"] for item in response.json()["results"]], expected
                )

    def test_category_vehicle_filters_and_combined_pagination(self):
        response = self.client.get(
            "/api/products/",
            {"category": "Brakes", "vehicle": "pUlSaR 150", "search": "endurance"},
        )
        self.assertEqual([item["sku"] for item in response.json()["results"]], ["BRK-TEST-01"])

        response = self.client.get(
            "/api/products/", {"category": "Brakes", "page_size": 1, "page": 2}
        )
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual([item["sku"] for item in response.json()["results"]], ["BRK-TEST-02"])

        exact_category = self.client.get("/api/products/?category=brakes")
        self.assertEqual(exact_category.json()["count"], 0)

    def test_create_product_initializes_stock_and_returns_contract_fields(self):
        response = self.client.post(
            "/api/products/", self._new_product_payload(), format="json"
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "sku",
                "name",
                "category",
                "brand",
                "vehicle_fitment",
                "price",
                "stock",
                "description",
            },
        )
        self.assertEqual(body["sku"], "ACC-NEW-01")
        self.assertEqual(body["price"], "875.25")
        self.assertEqual(body["stock"], 0)

    def test_duplicate_sku_uses_conflict_error(self):
        response = self.client.post(
            "/api/products/",
            self._new_product_payload(sku=self.product.sku),
            format="json",
        )
        self._assert_error(response, 409, "DUPLICATE")

    def test_invalid_prices_and_missing_fields_use_validation_error(self):
        for price in ("0", "-1.00", "1459.501", "not-money"):
            with self.subTest(price=price):
                response = self.client.post(
                    "/api/products/",
                    self._new_product_payload(price=price),
                    format="json",
                )
                self._assert_error(response, 400, "VALIDATION_ERROR")

        response = self.client.post(
            "/api/products/",
            self._new_product_payload(name=""),
            format="json",
        )
        self._assert_error(response, 400, "VALIDATION_ERROR")

    def test_create_rejects_stock_and_unknown_fields(self):
        response = self.client.post(
            "/api/products/",
            self._new_product_payload(stock=50),
            format="json",
        )
        self._assert_error(response, 400, "VALIDATION_ERROR")

    def test_malformed_json_uses_validation_error_without_trace(self):
        response = self.client.generic(
            "POST", "/api/products/", data="{", content_type="application/json"
        )
        self._assert_error(response, 400, "VALIDATION_ERROR")
        self.assertNotIn("Traceback", response.content.decode())

    def test_retrieve_existing_and_unknown_sku(self):
        response = self.client.get(f"/api/products/{self.product.sku}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sku"], self.product.sku)

        missing = self.client.get("/api/products/NO-SUCH-SKU/")
        self._assert_error(missing, 404, "NOT_FOUND")

    def test_patch_updates_only_supplied_fields(self):
        response = self.client.patch(
            f"/api/products/{self.product.sku}/", {"price": "1500.25"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["price"], "1500.25")
        self.assertEqual(body["name"], "Brake Pad Set")
        self.assertEqual(body["stock"], 12)

    def test_patch_rejects_sku_stock_and_invalid_price(self):
        url = f"/api/products/{self.product.sku}/"
        sku_change = self.client.patch(url, {"sku": "NEW-SKU"}, format="json")
        self._assert_error(sku_change, 400, "VALIDATION_ERROR")

        stock_change = self.client.patch(url, {"stock": 0}, format="json")
        self._assert_error(stock_change, 400, "VALIDATION_ERROR")

        bad_price = self.client.patch(url, {"price": "0.001"}, format="json")
        self._assert_error(bad_price, 400, "VALIDATION_ERROR")
        self.assertEqual(
            Product.objects.get(sku=self.product.sku).price, Decimal("1459.50")
        )


class InventoryAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.product = Product.objects.create(
            sku="INV-TEST-01",
            name="Inventory Test Part",
            category="Test",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("10.00"),
            stock=24,
            description="Inventory API fixture",
        )

    def _assert_validation_error(self, response):
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertIsInstance(body["error"]["message"], str)
        self.assertIsInstance(body["error"]["details"], list)

    def test_put_sets_absolute_quantity_and_returns_contract_shape(self):
        response = self.client.put(
            "/api/inventory/INV-TEST-01/",
            {"quantity": 30, "reason": "stock count correction"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sku": "INV-TEST-01", "quantity": 30})
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 30)
        self.assertEqual(self.product.price, Decimal("10.00"))
        self.assertEqual(self.product.name, "Inventory Test Part")

    def test_put_can_set_stock_to_zero(self):
        response = self.client.put(
            "/api/inventory/INV-TEST-01/",
            {"quantity": 0, "reason": "zero stock count"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sku": "INV-TEST-01", "quantity": 0})

    def test_put_rejects_negative_fractional_boolean_and_string_quantities(self):
        for quantity in (-1, 1.5, 1.0, True, "3"):
            with self.subTest(quantity=quantity):
                response = self.client.put(
                    "/api/inventory/INV-TEST-01/",
                    {"quantity": quantity, "reason": "invalid quantity test"},
                    format="json",
                )
                self._assert_validation_error(response)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 24)

    def test_put_rejects_missing_or_invalid_fields(self):
        invalid_bodies = (
            {"reason": "missing quantity"},
            {"quantity": 2},
            {"quantity": 2, "reason": "   "},
            {"quantity": 2, "reason": 4},
            {"quantity": 2, "reason": "count", "extra": "not allowed"},
        )
        for body in invalid_bodies:
            with self.subTest(body=body):
                response = self.client.put(
                    "/api/inventory/INV-TEST-01/", body, format="json"
                )
                self._assert_validation_error(response)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 24)

    def test_put_unknown_sku_returns_not_found_error(self):
        response = self.client.put(
            "/api/inventory/NO-SUCH-SKU/",
            {"quantity": 5, "reason": "count correction"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], "NOT_FOUND")
        self.assertIsInstance(body["error"]["message"], str)
        self.assertIsInstance(body["error"]["details"], list)


class DealersAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def _payload(self, **overrides):
        payload = {
            "dealer_code": "API-DLR-001",
            "name": "API Test Motors",
            "city": "Kochi",
            "phone": "9876543210",
            "email": "orders@example.com",
            "gstin": "27AABP5506A1Z6",
            "credit_limit": "125000.50",
        }
        payload.update(overrides)
        return payload

    def _assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"].get("message"), str)
        self.assertIsInstance(body["error"].get("details"), list)

    def test_list_is_paginated_with_contract_fields_and_deterministic_order(self):
        for number in range(25):
            Dealer.objects.create(
                dealer_code=f"PAGE-{number:03d}",
                name=f"Dealer {number:03d}",
            )

        default_page = self.client.get("/api/dealers/")
        self.assertEqual(default_page.status_code, 200)
        self.assertEqual(
            set(default_page.json()), {"count", "next", "previous", "results"}
        )
        self.assertEqual(default_page.json()["count"], 25)
        self.assertEqual(len(default_page.json()["results"]), 20)

        response = self.client.get("/api/dealers/?page_size=5&page=2")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 25)
        self.assertIsNotNone(body["next"])
        self.assertIsNotNone(body["previous"])
        self.assertEqual(len(body["results"]), 5)
        self.assertEqual(
            [dealer["dealer_code"] for dealer in body["results"]],
            ["PAGE-005", "PAGE-006", "PAGE-007", "PAGE-008", "PAGE-009"],
        )
        self.assertEqual(
            set(body["results"][0]),
            {"id", "dealer_code", "name", "city", "phone", "email", "gstin", "credit_limit"},
        )

    def test_create_returns_contract_fields_and_decimal_money(self):
        response = self.client.post("/api/dealers/", self._payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(
            set(body),
            {"id", "dealer_code", "name", "city", "phone", "email", "gstin", "credit_limit"},
        )
        self.assertIsInstance(body["id"], int)
        self.assertEqual(body["dealer_code"], "API-DLR-001")
        self.assertEqual(body["credit_limit"], "125000.50")

    def test_create_with_only_required_fields_uses_optional_defaults(self):
        response = self.client.post(
            "/api/dealers/",
            {"dealer_code": "API-DLR-MIN", "name": "Minimal Dealer"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json(),
            {
                "id": response.json()["id"],
                "dealer_code": "API-DLR-MIN",
                "name": "Minimal Dealer",
                "city": "",
                "phone": "",
                "email": "",
                "gstin": "",
                "credit_limit": "0.00",
            },
        )

    def test_duplicate_dealer_code_returns_conflict(self):
        Dealer.objects.create(dealer_code="API-DLR-001", name="Existing Dealer")

        response = self.client.post("/api/dealers/", self._payload(), format="json")

        self._assert_error(response, 409, "DUPLICATE")

    def test_required_and_optional_field_validation(self):
        invalid_payloads = (
            ({"name": "Missing code"}, "dealer_code"),
            ({"dealer_code": "API-DLR-NAME"}, "name"),
            (self._payload(email="not-an-email"), "email"),
            (self._payload(phone=9876543210), "phone"),
            (self._payload(phone="x" * 33), "phone"),
            (self._payload(gstin=123), "gstin"),
            (self._payload(gstin="x" * 33), "gstin"),
            (self._payload(credit_limit="not-money"), "credit_limit"),
            (self._payload(credit_limit="100.001"), "credit_limit"),
            (self._payload(credit_limit="100.5"), "credit_limit"),
            (self._payload(credit_limit=100.50), "credit_limit"),
            (self._payload(credit_limit="10000000000.00"), "credit_limit"),
            (self._payload(extra="not-allowed"), "extra"),
        )
        for payload, field in invalid_payloads:
            with self.subTest(field=field, payload=payload):
                response = self.client.post("/api/dealers/", payload, format="json")
                self._assert_error(response, 400, "VALIDATION_ERROR")

    def test_optional_blank_phone_email_and_gstin_are_allowed(self):
        response = self.client.post(
            "/api/dealers/",
            self._payload(phone="", email="", gstin=""),
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["phone"], "")
        self.assertEqual(response.json()["email"], "")
        self.assertEqual(response.json()["gstin"], "")

    def test_retrieve_existing_and_unknown_dealer(self):
        dealer = Dealer.objects.create(
            dealer_code="API-DLR-GET", name="Retrieve Dealer", credit_limit=Decimal("42.50")
        )

        response = self.client.get(f"/api/dealers/{dealer.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], dealer.pk)
        self.assertEqual(response.json()["dealer_code"], "API-DLR-GET")
        self.assertEqual(response.json()["credit_limit"], "42.50")

        missing = self.client.get("/api/dealers/999999/")
        self._assert_error(missing, 404, "NOT_FOUND")


class OrdersAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dealer = Dealer.objects.create(dealer_code="ORD-DLR-001", name="Order Dealer")
        self.first_product = Product.objects.create(
            sku="ORD-SKU-001",
            name="Small Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("0.03"),
            stock=8,
            description="Tax rounding fixture",
        )
        self.second_product = Product.objects.create(
            sku="ORD-SKU-002",
            name="Large Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("10.00"),
            stock=9,
            description="Second order fixture",
        )

    def _payload(self, **overrides):
        payload = {
            "dealer_id": self.dealer.pk,
            "items": [
                {"sku": self.first_product.sku, "quantity": 1},
                {"sku": self.second_product.sku, "quantity": 2},
            ],
        }
        payload.update(overrides)
        return payload

    def _assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"].get("message"), str)
        self.assertIsInstance(body["error"].get("details"), list)

    def test_create_multiple_items_calculates_decimal_totals_and_response(self):
        response = self.client.post("/api/orders/", self._payload(), format="json")

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(
            set(body),
            {
                "order_number",
                "dealer_id",
                "status",
                "items",
                "subtotal",
                "tax_total",
                "grand_total",
                "created_at",
                "updated_at",
            },
        )
        self.assertRegex(body["order_number"], r"^ORD-\d{8}-\d{4}$")
        self.assertEqual(body["dealer_id"], self.dealer.pk)
        self.assertEqual(body["status"], Order.Status.DRAFT)
        self.assertEqual(body["subtotal"], "20.03")
        self.assertEqual(body["tax_total"], "3.61")
        self.assertEqual(body["grand_total"], "23.64")
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(
            body["items"][0],
            {
                "sku": "ORD-SKU-001",
                "name": "Small Part",
                "quantity": 1,
                "unit_price": "0.03",
                "line_subtotal": "0.03",
                "line_tax": "0.01",
                "line_total": "0.04",
            },
        )
        self.assertEqual(body["items"][1]["line_tax"], "3.60")
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 8)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 9)

    def test_missing_invalid_and_empty_order_fields_return_validation_error(self):
        invalid_payloads = (
            ({"items": self._payload()["items"]}, "missing dealer"),
            ({"dealer_id": self.dealer.pk}, "missing items"),
            (self._payload(items=[]), "empty items"),
            (self._payload(dealer_id=True), "boolean dealer id"),
            (self._payload(dealer_id="invalid"), "invalid dealer id"),
            (self._payload(items=[{"sku": self.first_product.sku}]), "missing quantity"),
            (self._payload(items=[{"sku": self.first_product.sku, "quantity": 0}]), "zero quantity"),
            (self._payload(items=[{"sku": self.first_product.sku, "quantity": -1}]), "negative quantity"),
            (self._payload(items=[{"sku": self.first_product.sku, "quantity": 1.5}]), "fractional quantity"),
            (self._payload(items=[{"sku": self.first_product.sku, "quantity": True}]), "boolean quantity"),
            (self._payload(items=[{"sku": self.first_product.sku, "quantity": "2"}]), "string quantity"),
            (self._payload(items=[{"sku": 123, "quantity": 1}]), "non-string SKU"),
            (self._payload(items=[{"sku": self.first_product.sku, "quantity": 1, "extra": 1}]), "unknown item field"),
            (self._payload(extra=True), "unknown order field"),
        )
        for payload, case in invalid_payloads:
            with self.subTest(case=case):
                response = self.client.post("/api/orders/", payload, format="json")
                self._assert_error(response, 400, "VALIDATION_ERROR")
        self.assertEqual(Order.objects.count(), 0)

    def test_unknown_dealer_and_product_return_validation_error(self):
        unknown_dealer = self.client.post(
            "/api/orders/", self._payload(dealer_id=999999), format="json"
        )
        self._assert_error(unknown_dealer, 400, "VALIDATION_ERROR")

        unknown_product = self.client.post(
            "/api/orders/",
            self._payload(items=[{"sku": "NO-SUCH-SKU", "quantity": 1}]),
            format="json",
        )
        self._assert_error(unknown_product, 400, "VALIDATION_ERROR")
        self.assertEqual(Order.objects.count(), 0)

    def test_order_amounts_must_fit_existing_decimal_columns(self):
        expensive = Product.objects.create(
            sku="ORD-SKU-OVERFLOW",
            name="High Value Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("9999999999.99"),
            stock=0,
            description="Decimal boundary fixture",
        )
        response = self.client.post(
            "/api/orders/",
            self._payload(items=[{"sku": expensive.sku, "quantity": 2147483647}]),
            format="json",
        )
        self._assert_error(response, 400, "VALIDATION_ERROR")
        self.assertEqual(Order.objects.count(), 0)

    def test_repeated_sku_is_rejected(self):
        payload = self._payload(
            items=[
                {"sku": self.first_product.sku, "quantity": 1},
                {"sku": self.first_product.sku, "quantity": 2},
            ]
        )
        response = self.client.post("/api/orders/", payload, format="json")
        self._assert_error(response, 400, "VALIDATION_ERROR")
        self.assertEqual(Order.objects.count(), 0)

    def test_list_pagination_filters_and_retrieve_order(self):
        first = self.client.post("/api/orders/", self._payload(), format="json")
        second_dealer = Dealer.objects.create(
            dealer_code="ORD-DLR-002", name="Second Order Dealer"
        )
        second_payload = self._payload(dealer_id=second_dealer.pk)
        second = self.client.post("/api/orders/", second_payload, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)

        response = self.client.get("/api/orders/?page_size=1&page=1")
        self.assertEqual(response.status_code, 200)
        page = response.json()
        self.assertEqual(set(page), {"count", "next", "previous", "results"})
        self.assertEqual(page["count"], 2)
        self.assertEqual(len(page["results"]), 1)

        filtered = self.client.get(
            "/api/orders/", {"dealer_id": self.dealer.pk, "status": "DRAFT"}
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["count"], 1)
        self.assertEqual(filtered.json()["results"][0]["dealer_id"], self.dealer.pk)

        order_number = first.json()["order_number"]
        detail = self.client.get(f"/api/orders/{order_number}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json(), first.json())

        missing = self.client.get("/api/orders/ORD-20990101-9999/")
        self._assert_error(missing, 404, "NOT_FOUND")

    def test_idempotency_replays_original_order_for_same_request(self):
        payload = self._payload()
        first = self.client.post(
            "/api/orders/", payload, format="json", HTTP_IDEMPOTENCY_KEY="create-once"
        )
        replay = self.client.post(
            "/api/orders/", payload, format="json", HTTP_IDEMPOTENCY_KEY="create-once"
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_idempotency_key_with_different_body_returns_conflict(self):
        first = self.client.post(
            "/api/orders/",
            self._payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="same-key",
        )
        changed_payload = self._payload(
            items=[{"sku": self.first_product.sku, "quantity": 2}]
        )
        conflict = self.client.post(
            "/api/orders/",
            changed_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="same-key",
        )

        self.assertEqual(first.status_code, 201)
        self._assert_error(conflict, 409, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_invalid_idempotency_key_returns_validation_error(self):
        for key in ("", "x" * 256):
            with self.subTest(key_length=len(key)):
                response = self.client.post(
                    "/api/orders/",
                    self._payload(),
                    format="json",
                    HTTP_IDEMPOTENCY_KEY=key,
                )
                self._assert_error(response, 400, "VALIDATION_ERROR")
        self.assertEqual(Order.objects.count(), 0)

    @patch("core.services.IdempotencyRecord.objects.create", side_effect=DatabaseError("simulated record failure"))
    def test_idempotency_record_failure_rolls_back_order_and_sequence(self, _create_record):
        response = self.client.post(
            "/api/orders/",
            self._payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="rollback-key",
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(DailyOrderNumberSequence.objects.count(), 0)

    @patch("core.services.timezone.localdate", return_value=date(2026, 2, 3))
    def test_order_number_sequence_continues_per_day_and_resets_next_day(self, localdate):
        first = self.client.post("/api/orders/", self._payload(), format="json")
        second = self.client.post("/api/orders/", self._payload(), format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json()["order_number"], "ORD-20260203-0001")
        self.assertEqual(second.json()["order_number"], "ORD-20260203-0002")

        localdate.return_value = date(2026, 2, 4)
        next_day = self.client.post("/api/orders/", self._payload(), format="json")
        self.assertEqual(next_day.status_code, 201)
        self.assertEqual(next_day.json()["order_number"], "ORD-20260204-0001")


class OrderCreationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.dealer = Dealer.objects.create(
            dealer_code="CONCURRENT-DLR", name="Concurrency Dealer"
        )
        self.product = Product.objects.create(
            sku="CONCURRENT-SKU",
            name="Concurrent Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("10.00"),
            stock=100,
            description="Concurrency test part",
        )
        self.payload = {
            "dealer_id": self.dealer.pk,
            "items": [{"sku": self.product.sku, "quantity": 1}],
        }

    def _post_after_barrier(self, barrier, idempotency_key=None):
        db.close_old_connections()
        try:
            client = APIClient()
            barrier.wait(timeout=10)
            headers = {}
            if idempotency_key is not None:
                headers["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
            response = client.post("/api/orders/", self.payload, format="json", **headers)
            return response.status_code, response.json()
        finally:
            db.close_old_connections()

    def _run_concurrent_requests(self, idempotency_keys):
        barrier = Barrier(len(idempotency_keys))
        with ThreadPoolExecutor(max_workers=len(idempotency_keys)) as pool:
            futures = [
                pool.submit(self._post_after_barrier, barrier, key)
                for key in idempotency_keys
            ]
            return [future.result(timeout=30) for future in futures]

    def test_simultaneous_same_key_requests_create_one_order(self):
        responses = self._run_concurrent_requests(["parallel-key", "parallel-key"])

        self.assertCountEqual([status for status, _ in responses], [200, 201])
        self.assertEqual(responses[0][1], responses[1][1])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        self.assertEqual(DailyOrderNumberSequence.objects.get().last_sequence, 1)

    def test_simultaneous_distinct_requests_receive_unique_order_numbers(self):
        responses = self._run_concurrent_requests(["parallel-a", "parallel-b"])

        self.assertEqual([status for status, _ in responses], [201, 201])
        order_numbers = [body["order_number"] for _, body in responses]
        self.assertEqual(len(set(order_numbers)), 2)
        self.assertEqual(Order.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)
        self.assertEqual(DailyOrderNumberSequence.objects.get().last_sequence, 2)


class OrderLifecycleAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dealer = Dealer.objects.create(dealer_code="FLOW-DLR-001", name="Flow Dealer")
        self.first_product = Product.objects.create(
            sku="FLOW-SKU-001",
            name="First Flow Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("12.00"),
            stock=10,
            description="First item",
        )
        self.second_product = Product.objects.create(
            sku="FLOW-SKU-002",
            name="Second Flow Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("5.00"),
            stock=2,
            description="Second item",
        )
        response = self.client.post(
            "/api/orders/",
            {
                "dealer_id": self.dealer.pk,
                "items": [
                    {"sku": self.first_product.sku, "quantity": 3},
                    {"sku": self.second_product.sku, "quantity": 2},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.order_number = response.json()["order_number"]

    def _post_action(self, action, order_number=None):
        number = order_number or self.order_number
        return self.client.post(f"/api/orders/{number}/{action}/", {}, format="json")

    def _assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"].get("message"), str)
        self.assertIsInstance(body["error"].get("details"), list)

    def test_valid_full_transition_flow_and_confirmation_stock_decrement(self):
        initial_stock = {
            self.first_product.sku: 10,
            self.second_product.sku: 2,
        }
        confirmed = self._post_action("confirm")
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.json()["status"], Order.Status.CONFIRMED)
        self.assertEqual(
            Product.objects.get(pk=self.first_product.pk).stock,
            initial_stock[self.first_product.sku] - 3,
        )
        self.assertEqual(
            Product.objects.get(pk=self.second_product.pk).stock,
            initial_stock[self.second_product.sku] - 2,
        )
        self.assertEqual(confirmed.json()["items"][0]["unit_price"], "12.00")

        dispatched = self._post_action("dispatch")
        self.assertEqual(dispatched.status_code, 200)
        self.assertEqual(dispatched.json()["status"], Order.Status.DISPATCHED)

        delivered = self._post_action("deliver")
        self.assertEqual(delivered.status_code, 200)
        self.assertEqual(delivered.json()["status"], Order.Status.DELIVERED)
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 7)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 0)


@override_settings(
    SUPPLIER_API_URL="https://supplier.example",
    SUPPLIER_API_KEY="test-supplier-key",
)
class SupplierSyncAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.existing = Product.objects.create(
            sku="SUP-UPDATE",
            name="Existing Supplier Part",
            category="Parts",
            brand="Old Brand",
            vehicle_fitment="Universal",
            price=Decimal("10.00"),
            stock=77,
            description="Old description",
        )
        self.unchanged = Product.objects.create(
            sku="SUP-SAME",
            name="Unchanged Supplier Part",
            category="Parts",
            brand="Same Brand",
            vehicle_fitment="Universal",
            price=Decimal("20.50"),
            stock=15,
            description="Same description",
        )

    def _supplier_item(self, default_sku, **overrides):
        item = {
            "supplier_sku": f"EXT-{default_sku}",
            "sku": default_sku,
            "name": "New Supplier Part",
            "category": "Universal Accessories",
            "brand": "Moto Torque",
            "vehicle_fitment": "Universal",
            "description": "Supplier description",
            "price": "15.75",
            "supplier_stock": 999,
            "updated_at": "2026-10-10T10:00:00Z",
        }
        item.update(overrides)
        return item

    def _existing_item(self, product, **overrides):
        return self._supplier_item(
            product.sku,
            name=product.name,
            category=product.category,
            brand=product.brand,
            vehicle_fitment=product.vehicle_fitment,
            description=product.description,
            price=f"{product.price:.2f}",
            **overrides,
        )

    @staticmethod
    def _response(payload=None, status_code=200, headers=None, json_error=None):
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        if json_error:
            response.json.side_effect = json_error
        else:
            response.json.return_value = payload
        return response

    def _sync(self):
        return self.client.post("/api/sync/supplier/", {}, format="json")

    def _assert_supplier_unavailable(self, response):
        self.assertEqual(response.status_code, 502)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], "SUPPLIER_UNAVAILABLE")
        self.assertIsInstance(body["error"]["message"], str)
        self.assertIsInstance(body["error"]["details"], list)

    def test_successful_paginated_sync_updates_creates_deduplicates_and_preserves_stock(self):
        older_duplicate = self._supplier_item(
            "SUP-NEW", name="Older Version", price="2.00", updated_at="2026-10-01T00:00:00Z"
        )
        newer_duplicate = self._supplier_item(
            "SUP-NEW", name="Latest Version", price="3.00", updated_at="2026-10-11T00:00:00Z"
        )
        update_item = self._supplier_item(
            self.existing.sku,
            name="Updated Part",
            category="Brakes",
            brand="New Brand",
            vehicle_fitment="Bajaj Pulsar 150",
            description="Updated description",
            price="12.25",
        )
        invalid_sku = self._supplier_item("SUP-BAD-SKU", sku="")
        invalid_price = self._supplier_item("SUP-BAD-PRICE", price="12.345")
        first_page = self._response(
            {
                "items": [update_item, older_duplicate, invalid_sku, invalid_price],
                "next_cursor": "cursor-1",
            }
        )
        second_page = self._response(
            {
                "items": [newer_duplicate, self._existing_item(self.unchanged)],
                "next_cursor": None,
            }
        )

        with patch("core.supplier_sync.requests.get", side_effect=[first_page, second_page]) as get:
            response = self._sync()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "created": 1,
                "updated": 1,
                "unchanged": 1,
                "rejected": [
                    {"supplier_sku": "EXT-SUP-BAD-SKU", "reason": "missing or empty sku"},
                    {"supplier_sku": "EXT-SUP-BAD-PRICE", "reason": "invalid price"},
                ],
                "pages_fetched": 2,
                "requests_made": 2,
            },
        )
        self.assertEqual(get.call_count, 2)
        first_call = get.call_args_list[0]
        second_call = get.call_args_list[1]
        self.assertEqual(first_call.args[0], "https://supplier.example/v1/products")
        self.assertEqual(first_call.kwargs["params"], {"limit": 20})
        self.assertEqual(second_call.kwargs["params"], {"limit": 20, "cursor": "cursor-1"})
        self.assertEqual(first_call.kwargs["headers"], {"X-Api-Key": "test-supplier-key"})

        self.existing.refresh_from_db()
        self.unchanged.refresh_from_db()
        created = Product.objects.get(sku="SUP-NEW")
        self.assertEqual(self.existing.name, "Updated Part")
        self.assertEqual(self.existing.price, Decimal("12.25"))
        self.assertEqual(self.existing.stock, 77)
        self.assertEqual(self.unchanged.stock, 15)
        self.assertEqual(created.name, "Latest Version")
        self.assertEqual(created.price, Decimal("3.00"))
        self.assertEqual(created.stock, 0)

    def test_unchanged_feed_and_repeated_sync_do_not_create_or_change_stock(self):
        item = self._existing_item(self.existing)
        response_body = {"items": [item], "next_cursor": None}
        with patch(
            "core.supplier_sync.requests.get",
            side_effect=[self._response(response_body), self._response(response_body)],
        ):
            first = self._sync()
            second = self._sync()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["created"], 0)
        self.assertEqual(first.json()["updated"], 0)
        self.assertEqual(first.json()["unchanged"], 1)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["created"], 0)
        self.assertEqual(second.json()["updated"], 0)
        self.assertEqual(Product.objects.filter(sku=self.existing.sku).count(), 1)
        self.existing.refresh_from_db()
        self.assertEqual(self.existing.stock, 77)

    def test_invalid_identifiers_prices_and_required_fields_are_reported_and_skipped(self):
        items = [
            self._supplier_item("MISSING-SKU", sku=None),
            self._supplier_item("EMPTY-SKU", sku=""),
            self._supplier_item("MISSING-PRICE", price=None),
            self._supplier_item("ZERO-PRICE", price="0.00"),
            self._supplier_item("BAD-PRICE", price="N/A"),
            self._supplier_item("BAD-PRECISION", price="12.345"),
            self._supplier_item("MISSING-NAME", name=None),
            self._supplier_item("MISSING-TIMESTAMP", updated_at=None),
        ]
        with patch(
            "core.supplier_sync.requests.get",
            return_value=self._response({"items": items, "next_cursor": None}),
        ):
            response = self._sync()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 0)
        self.assertEqual(response.json()["updated"], 0)
        self.assertEqual(response.json()["unchanged"], 0)
        self.assertEqual(len(response.json()["rejected"]), len(items))
        self.assertEqual(Product.objects.count(), 2)

    def test_429_retries_same_page_and_counts_both_http_attempts(self):
        throttled = self._response(
            {"error": "rate limited"},
            status_code=429,
            headers={"Retry-After": "0"},
        )
        success = self._response({"items": [], "next_cursor": None})
        with patch("core.supplier_sync.time.sleep") as sleep, patch(
            "core.supplier_sync.requests.get", side_effect=[throttled, success]
        ) as get:
            response = self._sync()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["requests_made"], 2)
        self.assertEqual(response.json()["pages_fetched"], 1)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["params"], get.call_args_list[1].kwargs["params"])
        sleep.assert_called_once_with(0.0)

    def test_timeout_and_connection_failures_exhaust_five_attempts_without_writes(self):
        for error in (requests.Timeout("late"), requests.ConnectionError("offline")):
            with self.subTest(error=type(error).__name__):
                with patch("core.supplier_sync.time.sleep"), patch(
                    "core.supplier_sync.requests.get", side_effect=error
                ) as get:
                    response = self._sync()
                self._assert_supplier_unavailable(response)
                self.assertEqual(get.call_count, 5)
                self.assertEqual(Product.objects.count(), 2)

    def test_unauthorized_and_exhausted_server_errors_return_supplier_unavailable(self):
        unauthorized = self._response({"error": "invalid key"}, status_code=401)
        with patch("core.supplier_sync.requests.get", return_value=unauthorized) as get:
            response = self._sync()
        self._assert_supplier_unavailable(response)
        self.assertEqual(get.call_count, 1)

        unavailable = self._response({"error": "unavailable"}, status_code=503)
        with patch("core.supplier_sync.time.sleep"), patch(
            "core.supplier_sync.requests.get", return_value=unavailable
        ) as get:
            response = self._sync()
        self._assert_supplier_unavailable(response)
        self.assertEqual(get.call_count, 5)
        self.assertEqual(Product.objects.count(), 2)

    def test_malformed_page_envelope_fails_without_changes(self):
        malformed = self._response({"items": "not-a-list", "next_cursor": None})
        with patch("core.supplier_sync.requests.get", return_value=malformed):
            response = self._sync()

        self._assert_supplier_unavailable(response)
        self.assertEqual(Product.objects.count(), 2)

    def test_database_failure_rolls_back_all_local_feed_updates(self):
        new_item = self._supplier_item("SUP-A-NEW")
        update_item = self._supplier_item(
            self.existing.sku,
            name="Should Roll Back",
            category=self.existing.category,
            brand=self.existing.brand,
            vehicle_fitment=self.existing.vehicle_fitment,
            description=self.existing.description,
            price="11.00",
        )
        page = self._response({"items": [new_item, update_item], "next_cursor": None})
        original_save = Product.save

        def fail_update(product, *args, **kwargs):
            if product.sku == self.existing.sku and product.name == "Should Roll Back":
                raise DatabaseError("simulated update failure")
            return original_save(product, *args, **kwargs)

        with patch("core.supplier_sync.requests.get", return_value=page), patch(
            "core.supplier_sync.Product.save", new=fail_update
        ):
            response = self._sync()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertFalse(Product.objects.filter(sku="SUP-A-NEW").exists())
        self.existing.refresh_from_db()
        self.assertEqual(self.existing.name, "Existing Supplier Part")
        self.assertEqual(self.existing.stock, 77)


class OrderLifecycleContinuationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dealer = Dealer.objects.create(dealer_code="FLOW-DLR-001", name="Flow Dealer")
        self.first_product = Product.objects.create(
            sku="FLOW-SKU-001",
            name="First Flow Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("12.00"),
            stock=10,
            description="First item",
        )
        self.second_product = Product.objects.create(
            sku="FLOW-SKU-002",
            name="Second Flow Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("5.00"),
            stock=2,
            description="Second item",
        )
        response = self.client.post(
            "/api/orders/",
            {
                "dealer_id": self.dealer.pk,
                "items": [
                    {"sku": self.first_product.sku, "quantity": 3},
                    {"sku": self.second_product.sku, "quantity": 2},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.order_number = response.json()["order_number"]

    def _post_action(self, action, order_number=None):
        number = order_number or self.order_number
        return self.client.post(f"/api/orders/{number}/{action}/", {}, format="json")

    def _assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"].get("message"), str)
        self.assertIsInstance(body["error"].get("details"), list)

    def test_insufficient_stock_reports_every_short_line_without_changes(self):
        self.second_product.stock = 1
        self.second_product.save(update_fields=["stock"])
        self.first_product.stock = 2
        self.first_product.save(update_fields=["stock"])

        response = self._post_action("confirm")

        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["error"]["code"], "INSUFFICIENT_STOCK")
        self.assertIsInstance(body["error"]["message"], str)
        self.assertEqual(
            body["error"]["details"],
            [
                {"sku": "FLOW-SKU-001", "requested": 3, "available": 2},
                {"sku": "FLOW-SKU-002", "requested": 2, "available": 1},
            ],
        )
        order = Order.objects.get(order_number=self.order_number)
        self.assertEqual(order.status, Order.Status.DRAFT)
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 2)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 1)

    def test_invalid_transitions_return_conflict_and_do_not_change_stock(self):
        invalid_calls = (
            "dispatch",
            "deliver",
        )
        for action in invalid_calls:
            with self.subTest(action=action):
                self._assert_error(self._post_action(action), 409, "INVALID_TRANSITION")

        confirmed = self._post_action("confirm")
        self.assertEqual(confirmed.status_code, 200)
        for action in ("confirm", "deliver"):
            with self.subTest(action=action, state="CONFIRMED"):
                self._assert_error(self._post_action(action), 409, "INVALID_TRANSITION")

        self.assertEqual(Order.objects.get(order_number=self.order_number).status, Order.Status.CONFIRMED)
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 7)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 0)

    def test_draft_cancel_does_not_change_stock_and_repeated_cancel_is_rejected(self):
        response = self._post_action("cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], Order.Status.CANCELLED)
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 2)

        self._assert_error(self._post_action("cancel"), 409, "INVALID_TRANSITION")
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 2)

    def test_confirmed_cancel_restores_stock_exactly_once(self):
        self.assertEqual(self._post_action("confirm").status_code, 200)
        cancelled = self._post_action("cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], Order.Status.CANCELLED)
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 2)

        self._assert_error(self._post_action("cancel"), 409, "INVALID_TRANSITION")
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 2)

    def test_dispatched_order_cannot_be_cancelled(self):
        self.assertEqual(self._post_action("confirm").status_code, 200)
        self.assertEqual(self._post_action("dispatch").status_code, 200)
        self._assert_error(self._post_action("cancel"), 409, "INVALID_TRANSITION")
        self.assertEqual(Order.objects.get(order_number=self.order_number).status, Order.Status.DISPATCHED)
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 7)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 0)

    def test_stock_write_failure_rolls_back_all_stock_and_order_status(self):
        original_save = Product.save
        save_count = 0

        def fail_after_one_stock_write(product, *args, **kwargs):
            nonlocal save_count
            save_count += 1
            if save_count == 2:
                raise DatabaseError("simulated stock write failure")
            return original_save(product, *args, **kwargs)

        with patch("core.services.Product.save", new=fail_after_one_stock_write):
            response = self._post_action("confirm")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(Order.objects.get(order_number=self.order_number).status, Order.Status.DRAFT)
        self.assertEqual(Product.objects.get(pk=self.first_product.pk).stock, 10)
        self.assertEqual(Product.objects.get(pk=self.second_product.pk).stock, 2)

    def test_unknown_order_transition_returns_not_found(self):
        response = self._post_action("confirm", "ORD-20990101-9999")
        self._assert_error(response, 404, "NOT_FOUND")


class OrderEditAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dealer = Dealer.objects.create(dealer_code="EDIT-DLR-001", name="Edit Dealer")
        self.first_product = Product.objects.create(
            sku="EDIT-SKU-001",
            name="First Edit Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("10.00"),
            stock=25,
            description="First part",
        )
        self.second_product = Product.objects.create(
            sku="EDIT-SKU-002",
            name="Second Edit Part",
            category="Parts",
            brand="Test Brand",
            vehicle_fitment="Universal",
            price=Decimal("0.03"),
            stock=8,
            description="Second part",
        )
        response = self.client.post(
            "/api/orders/",
            {
                "dealer_id": self.dealer.pk,
                "items": [{"sku": self.first_product.sku, "quantity": 1}],
            },
            format="json",
            HTTP_IDEMPOTENCY_KEY="edit-order-key",
        )
        self.assertEqual(response.status_code, 201)
        self.initial_order = response.json()
        self.order_number = self.initial_order["order_number"]

    def _put_items(self, items, **extra_fields):
        payload = {"items": items, **extra_fields}
        return self.client.put(
            f"/api/orders/{self.order_number}/", payload, format="json"
        )

    def _assert_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        body = response.json()
        self.assertEqual(set(body), {"error"})
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"].get("message"), str)
        self.assertIsInstance(body["error"].get("details"), list)

    def test_draft_put_replaces_items_recalculates_totals_and_preserves_identity(self):
        self.first_product.price = Decimal("12.00")
        self.first_product.save(update_fields=["price"])
        original_stock = {
            self.first_product.sku: self.first_product.stock,
            self.second_product.sku: self.second_product.stock,
        }

        response = self._put_items(
            [
                {"sku": self.first_product.sku, "quantity": 2},
                {"sku": self.second_product.sku, "quantity": 3},
            ]
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["order_number"], self.order_number)
        self.assertEqual(body["dealer_id"], self.dealer.pk)
        self.assertEqual(body["status"], Order.Status.DRAFT)
        self.assertEqual(body["subtotal"], "24.09")
        self.assertEqual(body["tax_total"], "4.34")
        self.assertEqual(body["grand_total"], "28.43")
        self.assertEqual(
            [(item["sku"], item["quantity"]) for item in body["items"]],
            [("EDIT-SKU-001", 2), ("EDIT-SKU-002", 3)],
        )
        self.assertEqual(body["items"][0]["unit_price"], "12.00")
        self.assertEqual(body["items"][1]["line_tax"], "0.02")
        self.assertEqual(OrderItem.objects.filter(order__order_number=self.order_number).count(), 2)
        self.assertEqual(
            IdempotencyRecord.objects.get(key="edit-order-key").order.order_number,
            self.order_number,
        )
        for sku, stock in original_stock.items():
            self.assertEqual(Product.objects.get(pk=sku).stock, stock)

    def test_missing_order_returns_not_found(self):
        response = self.client.put(
            "/api/orders/ORD-20990101-9999/",
            {"items": [{"sku": self.first_product.sku, "quantity": 1}]},
            format="json",
        )
        self._assert_error(response, 404, "NOT_FOUND")

    def test_malformed_json_returns_validation_error_without_mutating_order(self):
        order = Order.objects.get(order_number=self.order_number)
        items_before = list(
            OrderItem.objects.filter(order=order).values_list(
                "product_id", "quantity", "unit_price", "line_subtotal", "line_tax", "line_total"
            )
        )

        response = self.client.generic(
            "PUT",
            f"/api/orders/{self.order_number}/",
            data="{",
            content_type="application/json",
        )

        self._assert_error(response, 400, "VALIDATION_ERROR")
        self.assertEqual(
            list(
                OrderItem.objects.filter(order=order).values_list(
                    "product_id", "quantity", "unit_price", "line_subtotal", "line_tax", "line_total"
                )
            ),
            items_before,
        )

    def test_invalid_replacement_inputs_leave_original_items_and_totals(self):
        invalid_payloads = (
            ({}, "missing items"),
            ({"items": []}, "empty items"),
            ({"items": [{"sku": "UNKNOWN-SKU", "quantity": 1}]}, "unknown SKU"),
            ({"items": [{"sku": self.first_product.sku}]}, "missing quantity"),
            ({"items": [{"sku": self.first_product.sku, "quantity": 0}]}, "zero quantity"),
            ({"items": [{"sku": self.first_product.sku, "quantity": 1.5}]}, "fractional quantity"),
            ({"items": [{"sku": self.first_product.sku, "quantity": True}]}, "boolean quantity"),
            (
                {
                    "items": [
                        {"sku": self.first_product.sku, "quantity": 1},
                        {"sku": self.first_product.sku, "quantity": 2},
                    ]
                },
                "duplicate SKU",
            ),
            (
                {"items": [{"sku": self.first_product.sku, "quantity": 1}], "dealer_id": self.dealer.pk},
                "unsupported field",
            ),
        )
        initial_items = list(
            OrderItem.objects.filter(order__order_number=self.order_number).values_list(
                "product_id", "quantity", "unit_price", "line_subtotal", "line_tax", "line_total"
            )
        )
        initial_order = Order.objects.get(order_number=self.order_number)
        initial_totals = (initial_order.subtotal, initial_order.tax_total, initial_order.grand_total)

        for payload, case in invalid_payloads:
            with self.subTest(case=case):
                response = self.client.put(
                    f"/api/orders/{self.order_number}/", payload, format="json"
                )
                self._assert_error(response, 400, "VALIDATION_ERROR")

        self.assertEqual(
            list(
                OrderItem.objects.filter(order__order_number=self.order_number).values_list(
                    "product_id", "quantity", "unit_price", "line_subtotal", "line_tax", "line_total"
                )
            ),
            initial_items,
        )
        initial_order.refresh_from_db()
        self.assertEqual(
            (initial_order.subtotal, initial_order.tax_total, initial_order.grand_total),
            initial_totals,
        )

    def test_non_draft_orders_return_order_locked(self):
        order = Order.objects.get(order_number=self.order_number)
        for status_value in (
            Order.Status.CONFIRMED,
            Order.Status.DISPATCHED,
            Order.Status.DELIVERED,
            Order.Status.CANCELLED,
        ):
            with self.subTest(status=status_value):
                order.status = status_value
                order.save(update_fields=["status"])
                response = self._put_items(
                    [{"sku": self.second_product.sku, "quantity": 2}]
                )
                self._assert_error(response, 409, "ORDER_LOCKED")
                order.refresh_from_db()
                self.assertEqual(order.status, status_value)
                self.assertEqual(
                    list(OrderItem.objects.filter(order=order).values_list("product_id", "quantity")),
                    [(self.first_product.sku, 1)],
                )

    @patch("core.views.OrderItem.objects.bulk_create", side_effect=DatabaseError("simulated replacement failure"))
    def test_database_failure_rolls_back_deleted_items_and_totals(self, _bulk_create):
        order = Order.objects.get(order_number=self.order_number)
        original_item = OrderItem.objects.get(order=order)
        original_totals = (order.subtotal, order.tax_total, order.grand_total)

        response = self._put_items(
            [{"sku": self.second_product.sku, "quantity": 4}]
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        order.refresh_from_db()
        self.assertEqual(
            (order.subtotal, order.tax_total, order.grand_total), original_totals
        )
        restored_item = OrderItem.objects.get(order=order)
        self.assertEqual(restored_item.pk, original_item.pk)
        self.assertEqual(restored_item.product_id, self.first_product.sku)
        self.assertEqual(restored_item.quantity, 1)