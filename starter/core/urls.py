from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("products/", views.ProductListCreateView.as_view(), name="product-list"),
    path("products/<str:sku>/", views.ProductDetailView.as_view(), name="product-detail"),
    path("inventory/<str:sku>/", views.InventoryUpdateView.as_view(), name="inventory-update"),
    path("dealers/", views.DealerListCreateView.as_view(), name="dealer-list"),
    path("dealers/<int:pk>/", views.DealerDetailView.as_view(), name="dealer-detail"),
    path("orders/", views.OrderListCreateView.as_view(), name="order-list"),
    path("orders/<str:order_number>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:order_number>/confirm/", views.OrderTransitionView.as_view(action="confirm"), name="order-confirm"),
    path("orders/<str:order_number>/dispatch/", views.OrderTransitionView.as_view(action="dispatch"), name="order-dispatch"),
    path("orders/<str:order_number>/deliver/", views.OrderTransitionView.as_view(action="deliver"), name="order-deliver"),
    path("orders/<str:order_number>/cancel/", views.OrderTransitionView.as_view(action="cancel"), name="order-cancel"),
    path("sync/supplier/", views.SupplierSyncView.as_view(), name="supplier-sync"),
]
