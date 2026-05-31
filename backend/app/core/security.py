from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


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
