"""Zero-trust JWT authentication.

Every service verifies the JWT *signature itself* using the shared
``JWT_SIGNING_KEY`` and reads identity from the token's own claims. Gateway
headers such as ``X-User-Role`` are never trusted for authorization — a request
that presents only such a header (and no valid bearer token) is anonymous.
"""

import jwt
from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed


class SimpleUser:
    """Lightweight principal built from JWT claims — no DB lookup.

    Business services are stateless resource servers; they do not own the User
    table, so identity comes entirely from the verified token.
    """

    def __init__(self, user_id: str, role: str, tenant_id: str):
        self.id = user_id
        self.pk = user_id
        self.role = role
        self.tenant_id = tenant_id

    @property
    def is_authenticated(self) -> bool:
        return True

    def __str__(self) -> str:
        return f"SimpleUser(id={self.id}, role={self.role})"


class JWTAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None  # no bearer token -> anonymous (headers carry no authority)
        if len(auth) != 2:
            raise AuthenticationFailed("Invalid Authorization header.")

        token = auth[1].decode()
        try:
            claims = jwt.decode(
                token,
                settings.JWT_SIGNING_KEY,
                algorithms=["HS256"],
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationFailed("Invalid or expired token.") from exc

        try:
            user = SimpleUser(
                user_id=claims["sub"],
                role=claims["role"],
                tenant_id=claims["tenant"],
            )
        except KeyError as exc:
            raise AuthenticationFailed(f"Token missing required claim: {exc}") from exc

        # Expose tenant to TenantMiddleware without trusting any request header.
        request.tenant_id = user.tenant_id
        return (user, claims)

    def authenticate_header(self, request):
        return self.keyword
