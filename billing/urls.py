from django.urls import path
from . import views

app_name = "billing"
urlpatterns = [
    path("", views.pricing, name="pricing"),
    path("checkout/<int:plan_id>/", views.checkout, name="checkout"),
    path("orders/<uuid:reference>/", views.status, name="status"),
    path("orders/<uuid:reference>/confirmation/", views.confirmation, name="confirmation"),
    path("orders/<uuid:reference>/simulate/", views.simulate, name="simulate"),
]
