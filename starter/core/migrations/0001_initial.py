from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Dealer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dealer_code", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=255)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("phone", models.CharField(blank=True, max_length=32)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("gstin", models.CharField(blank=True, max_length=32)),
                ("credit_limit", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
            ],
        ),
        migrations.CreateModel(
            name="DailyOrderNumberSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence_date", models.DateField(unique=True)),
                ("last_sequence", models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("sku", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("category", models.CharField(db_index=True, max_length=100)),
                ("brand", models.CharField(db_index=True, max_length=100)),
                ("vehicle_fitment", models.CharField(max_length=255)),
                ("price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("stock", models.PositiveIntegerField(default=0)),
                ("description", models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order_number", models.CharField(max_length=32, unique=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("CONFIRMED", "Confirmed"), ("DISPATCHED", "Dispatched"), ("DELIVERED", "Delivered"), ("CANCELLED", "Cancelled")], db_index=True, default="DRAFT", max_length=16)),
                ("subtotal", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("tax_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("grand_total", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("dealer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="orders", to="core.dealer")),
            ],
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("quantity", models.PositiveIntegerField()),
                ("unit_price", models.DecimalField(decimal_places=2, max_digits=12)),
                ("line_subtotal", models.DecimalField(decimal_places=2, max_digits=14)),
                ("line_tax", models.DecimalField(decimal_places=2, max_digits=14)),
                ("line_total", models.DecimalField(decimal_places=2, max_digits=14)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="core.order")),
                ("product", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="order_items", to="core.product")),
            ],
        ),
        migrations.CreateModel(
            name="IdempotencyRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=255, unique=True)),
                ("request_hash", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="idempotency_records", to="core.order")),
            ],
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(check=models.Q(price__gt=0), name="product_price_positive"),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(check=models.Q(stock__gte=0), name="product_stock_nonnegative"),
        ),
        migrations.AddConstraint(
            model_name="dailyordernumbersequence",
            constraint=models.CheckConstraint(check=models.Q(last_sequence__gte=0), name="order_sequence_nonnegative"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["dealer", "status"], name="order_dealer_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.UniqueConstraint(fields=("order", "product"), name="order_item_product_unique"),
        ),
        migrations.AddConstraint(
            model_name="orderitem",
            constraint=models.CheckConstraint(check=models.Q(quantity__gte=1), name="order_item_quantity_positive"),
        ),
        migrations.AddIndex(
            model_name="idempotencyrecord",
            index=models.Index(fields=["created_at"], name="idempotency_created_idx"),
        ),
    ]