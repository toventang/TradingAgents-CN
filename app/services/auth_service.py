import logging
import time
from datetime import timedelta
from typing import Any, Mapping, Optional

import jwt
from pydantic import BaseModel, Field

from app.core.config import settings
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


class TokenData(BaseModel):
    sub: str = Field(min_length=1)
    exp: int


class AuthenticatedIdentity(BaseModel):
    """Canonical authenticated identity shared by HTTP-adjacent components."""

    user_id: str = Field(min_length=1)
    username: str = Field(min_length=1)
    is_admin: bool = False
    roles: list[str] = Field(default_factory=lambda: ["user"])

    def as_http_user(self) -> dict[str, Any]:
        """Return the identity shape already consumed by HTTP dependencies."""
        return {
            "id": self.user_id,
            "username": self.username,
            "name": self.username,
            "is_admin": self.is_admin,
            "roles": list(self.roles),
        }


def _user_value(user: Any, key: str, default: Any = None) -> Any:
    if isinstance(user, Mapping):
        return user.get(key, default)
    return getattr(user, key, default)


class AuthService:
    @staticmethod
    def create_access_token(
        sub: str,
        expires_minutes: int | None = None,
        expires_delta: int | None = None,
    ) -> str:
        if expires_delta is not None:
            expire = now_tz() + timedelta(seconds=expires_delta)
        else:
            expire = now_tz() + timedelta(
                minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
            )
        payload = {"sub": sub, "exp": expire}
        return jwt.encode(
            payload,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

    @staticmethod
    def verify_token(token: str) -> Optional[TokenData]:
        """Verify a JWT without logging the token, payload, or secret material."""
        if not isinstance(token, str) or not token.strip():
            return None

        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                options={"require": ["sub", "exp"]},
            )
            subject = payload.get("sub")
            if not isinstance(subject, str) or not subject.strip():
                return None

            token_data = TokenData(sub=subject.strip(), exp=int(payload["exp"]))
            if token_data.exp < int(time.time()):
                return None
            return token_data
        except jwt.ExpiredSignatureError:
            logger.warning("JWT verification failed: token expired")
        except jwt.InvalidTokenError:
            logger.warning("JWT verification failed: invalid token")
        except (TypeError, ValueError):
            logger.warning("JWT verification failed: malformed claims")
        except Exception as exc:
            logger.error(
                "JWT verification failed unexpectedly error_type=%s",
                type(exc).__name__,
            )
            return None

    @staticmethod
    def identity_from_verified_token(
        token_data: TokenData,
        user: Any,
    ) -> Optional[AuthenticatedIdentity]:
        """Convert verified claims plus their database user into one identity."""
        if token_data is None or user is None:
            return None

        username = _user_value(user, "username")
        user_id = _user_value(user, "id", _user_value(user, "_id"))
        is_active = bool(_user_value(user, "is_active", True))
        if (
            not is_active
            or not username
            or not user_id
            or str(username) != token_data.sub
        ):
            return None

        is_admin = bool(_user_value(user, "is_admin", False))
        return AuthenticatedIdentity(
            user_id=str(user_id),
            username=str(username),
            is_admin=is_admin,
            roles=["admin"] if is_admin else ["user"],
        )

    @staticmethod
    async def authenticate_token(token: str) -> Optional[AuthenticatedIdentity]:
        """Resolve a verified legacy username-subject token to the real user ID."""
        token_data = AuthService.verify_token(token)
        if token_data is None:
            return None

        try:
            from app.services.user_service import user_service

            user = await user_service.get_user_by_username(token_data.sub)
        except Exception as exc:
            logger.error(
                "Authenticated user lookup failed error_type=%s",
                type(exc).__name__,
            )
            return None
        return AuthService.identity_from_verified_token(token_data, user)
