from django.urls import path

from media import views

urlpatterns = [
    path("media/resolve", views.resolve_assets),
    path("media/<uuid:asset_id>", views.get_asset),
    path("uploads", views.start_upload),
    path("uploads/<uuid:session_id>/grant", views.refresh_grant),
    path("uploads/<uuid:session_id>/attach", views.attach_upload),
]
