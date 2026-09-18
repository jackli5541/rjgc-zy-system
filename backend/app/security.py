import hashlib
import secrets
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.settings import settings


password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_session() -> tuple[str, str, str, datetime]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    return token, hashlib.sha256(token.encode()).hexdigest(), csrf, datetime.now(UTC) + timedelta(hours=settings.session_hours)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
