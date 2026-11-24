import hashlib
import hmac
import secrets

from sqlalchemy import select

from .models import memberships, users


def hash_password(password, *, salt=None):
    if not 12 <= len(password) <= 256:
        raise ValueError("Password must contain 12 to 256 characters")
    salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1,
                            maxmem=64 * 1024 * 1024)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt = bytes.fromhex(stored.split(":", 1)[0])
        candidate = hash_password(password, salt=salt)
    except ValueError:
        return False
    return hmac.compare_digest(stored, candidate)


def require_project(connection, user_id, project_id, roles):
    admin = connection.execute(
        select(users.c.platform_admin).where(users.c.id == user_id)
    ).scalar_one_or_none()
    if admin == 1:
        return
    role = connection.execute(
        select(memberships.c.role).where(
            memberships.c.user_id == user_id, memberships.c.project_id == project_id,
        )
    ).scalar_one_or_none()
    if role not in roles:
        raise PermissionError("Project access denied")

