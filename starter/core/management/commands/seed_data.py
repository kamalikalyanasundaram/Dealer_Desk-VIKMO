import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from core.models import Dealer, Product


CATALOGUE_HEADERS = (
    "sku",
    "name",
    "category",
    "brand",
    "vehicle_fitment",
    "price",
    "stock",
    "description",
)
DEALER_HEADERS = (
    "dealer_code",
    "name",
    "city",
    "phone",
    "email",
    "gstin",
    "credit_limit",
)


class Command(BaseCommand):
    help = "Load catalogue.csv and dealers.csv without overwriting existing records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            type=Path,
            help="Use a data directory other than the configured project data directory.",
        )

    def handle(self, *args, **options):
        data_dir = options["data_dir"] or settings.DATA_DIR
        catalogue_rows = self._read_rows(
            data_dir / "catalogue.csv", CATALOGUE_HEADERS, "sku", self._product_from_row
        )
        dealer_rows = self._read_rows(
            data_dir / "dealers.csv", DEALER_HEADERS, "dealer_code", self._dealer_from_row
        )

        products_created = 0
        dealers_created = 0
        try:
            with transaction.atomic():
                for product in catalogue_rows:
                    _, created = Product.objects.get_or_create(
                        sku=product.sku,
                        defaults={
                            "name": product.name,
                            "category": product.category,
                            "brand": product.brand,
                            "vehicle_fitment": product.vehicle_fitment,
                            "price": product.price,
                            "stock": product.stock,
                            "description": product.description,
                        },
                    )
                    products_created += int(created)

                for dealer in dealer_rows:
                    _, created = Dealer.objects.get_or_create(
                        dealer_code=dealer.dealer_code,
                        defaults={
                            "name": dealer.name,
                            "city": dealer.city,
                            "phone": dealer.phone,
                            "email": dealer.email,
                            "gstin": dealer.gstin,
                            "credit_limit": dealer.credit_limit,
                        },
                    )
                    dealers_created += int(created)
        except DatabaseError as exc:
            raise CommandError(
                f"Database import failed; all seed changes were rolled back: {exc}"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed complete: products created={products_created}, "
                f"preserved_existing={len(catalogue_rows) - products_created}; "
                f"dealers created={dealers_created}, "
                f"preserved_existing={len(dealer_rows) - dealers_created}."
            )
        )

    def _read_rows(self, path, expected_headers, identifier, row_factory):
        if not path.is_file():
            raise CommandError(f"Required input file not found: {path}")

        records = []
        seen_identifiers = set()
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.reader(source, strict=True)
                headers = next(reader, None)
                if headers != list(expected_headers):
                    actual = headers if headers is not None else "<empty file>"
                    raise CommandError(
                        f"{path.name}:1: expected columns {list(expected_headers)!r}; "
                        f"found {actual!r}."
                    )

                for row in reader:
                    line_number = reader.line_num
                    if not row:
                        raise CommandError(f"{path.name}:{line_number}: empty row.")
                    if len(row) != len(expected_headers):
                        raise CommandError(
                            f"{path.name}:{line_number}: expected {len(expected_headers)} "
                            f"columns, found {len(row)}."
                        )

                    values = dict(zip(expected_headers, row))
                    record = row_factory(values, path.name, line_number)
                    key = getattr(record, identifier)
                    if key in seen_identifiers:
                        raise CommandError(
                            f"{path.name}:{line_number}: duplicate {identifier} {key!r}."
                        )
                    seen_identifiers.add(key)
                    records.append(record)
        except (OSError, UnicodeError, csv.Error) as exc:
            raise CommandError(f"Could not read {path}: {exc}") from exc

        return records

    def _product_from_row(self, values, filename, line_number):
        price = self._decimal(values["price"], filename, line_number, "price")
        if price <= 0:
            raise CommandError(f"{filename}:{line_number}: price must be greater than zero.")
        if price.as_tuple().exponent < -2:
            raise CommandError(
                f"{filename}:{line_number}: price must have at most two decimal places."
            )

        stock_text = values["stock"].strip()
        if not stock_text.isascii() or not stock_text.isdigit():
            raise CommandError(
                f"{filename}:{line_number}: stock must be an integer greater than or equal to zero."
            )

        product = Product(
            sku=values["sku"],
            name=values["name"],
            category=values["category"],
            brand=values["brand"],
            vehicle_fitment=values["vehicle_fitment"],
            price=price,
            stock=int(stock_text),
            description=values["description"],
        )
        self._validate_model(product, filename, line_number)
        return product

    def _dealer_from_row(self, values, filename, line_number):
        dealer = Dealer(
            dealer_code=values["dealer_code"],
            name=values["name"],
            city=values["city"],
            phone=values["phone"],
            email=values["email"],
            gstin=values["gstin"],
            credit_limit=self._decimal(
                values["credit_limit"], filename, line_number, "credit_limit"
            ),
        )
        self._validate_model(dealer, filename, line_number)
        return dealer

    def _decimal(self, value, filename, line_number, field_name):
        try:
            result = Decimal(value.strip())
        except (InvalidOperation, AttributeError):
            raise CommandError(
                f"{filename}:{line_number}: {field_name} must be a valid decimal amount."
            ) from None
        if not result.is_finite():
            raise CommandError(
                f"{filename}:{line_number}: {field_name} must be a finite decimal amount."
            )
        return result

    def _validate_model(self, instance, filename, line_number):
        try:
            instance.full_clean(validate_unique=False, validate_constraints=False)
        except ValidationError as exc:
            raise CommandError(
                f"{filename}:{line_number}: invalid record: {exc.message_dict}"
            ) from exc
