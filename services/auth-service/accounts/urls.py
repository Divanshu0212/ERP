"""Auth endpoints: register, login, refresh, me, institution, users."""

from accounts.views import (
    InstitutionView,
    LoginView,
    MeView,
    RefreshView,
    RegisterView,
    UserAdminView,
)
from django.urls import path

urlpatterns = [
    path("register", RegisterView.as_view(), name="auth-register"),
    path("login", LoginView.as_view(), name="auth-login"),
    path("refresh", RefreshView.as_view(), name="auth-refresh"),
    path("me", MeView.as_view(), name="auth-me"),
    path("institution", InstitutionView.as_view(), name="auth-institution"),
    path("users", UserAdminView.as_view(), name="auth-users"),
]
