from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt is used directly rather than through passlib: passlib 1.7.4 (its final
# release) crashes its backend self-test against bcrypt >= 4.1 / 5.x. The bcrypt
# algorithm only consumes the first 72 bytes of the password; we truncate to
# match that limit (bcrypt >= 4 raises on longer input) and to stay compatible
# with hashes previously produced via passlib's bcrypt backend.
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    pwd = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pwd, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload.get("sub")
    except JWTError:
        return None


def get_fernet() -> Fernet:
    key = settings.credential_fernet_key
    if not key:
        raise RuntimeError(
            "Fernet key not configured — set CREDENTIAL_FERNET_KEY env var "
            "(base64-encoded 32-byte key). Required when osa_multi_provider_llm=True."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_credential(plaintext: str) -> bytes:
    return get_fernet().encrypt(plaintext.encode())


def decrypt_credential(ciphertext: bytes) -> str:
    return get_fernet().decrypt(ciphertext).decode()
