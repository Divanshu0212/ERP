"""Auth endpoints: register, login, refresh, me, institution, users."""

from accounts.views import (
    DeviceListView,
    DeviceRevokeView,
    InstitutionView,
    LoginView,
    LogoutView,
    MeView,
    MyProfileView,
    PlatformAdminView,
    PlatformInstitutionView,
    RefreshView,
    RegisterView,
    UserAdminView,
    UserBulkCreateView,
    UserBulkDeactivateView,
    UserByCodeView,
    UserProfileView,
)
from django.urls import path

urlpatterns = [
    path("register", RegisterView.as_view(), name="auth-register"),
    path("login", LoginView.as_view(), name="auth-login"),
    path("refresh", RefreshView.as_view(), name="auth-refresh"),
    path("logout", LogoutView.as_view(), name="auth-logout"),
    path("devices", DeviceListView.as_view(), name="auth-devices"),
    path("devices/<str:device_id>", DeviceRevokeView.as_view(), name="auth-device-revoke"),
    path("me", MeView.as_view(), name="auth-me"),
    path("institution", InstitutionView.as_view(), name="auth-institution"),
    path("users", UserAdminView.as_view(), name="auth-users"),
    path("users/bulk/", UserBulkCreateView.as_view(), name="auth-users-bulk"),
    path("users/bulk-delete/", UserBulkDeactivateView.as_view(), name="auth-users-bulk-delete"),
    path("users/by-code/", UserByCodeView.as_view(), name="auth-user-by-code"),
    path("users/me/profile/", MyProfileView.as_view(), name="auth-my-profile"),
    path("users/<str:user_code>/profile/", UserProfileView.as_view(), name="auth-user-profile"),
    path("institutions", PlatformInstitutionView.as_view(), name="auth-institutions"),
    path("admins", PlatformAdminView.as_view(), name="auth-admins"),
]
