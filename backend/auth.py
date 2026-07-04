"""
auth.py — JWT-based authentication for Blitz Trader.

Credentials are read from env vars:
  IBKR_USERNAME  — your IBKR / TWS username
  IBKR_PASSWORD  — your IBKR / TWS password

A secret signing key is read from:
  JWT_SECRET     — random secret used to sign tokens (set this in Railway env vars)
                   if not set, a random one is generated per process (tokens invalidated on restart)
"""

import os
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

_env_secret = os.getenv("JWT_SECRET")
if not _env_secret:
    _env_secret = secrets.token_hex(32)
    logger.warning("JWT_SECRET not set — using a random secret. Tokens will be invalidated on restart.")

JWT_SECRET: str = _env_secret

IBKR_USERNAME: str = os.getenv("IB_USER", "")
IBKR_PASSWORD: str = os.getenv("IB_PASS", "")

# ─── Bearer scheme (auto extracts Authorization: Bearer <token>) ───────────────

_bearer_scheme = HTTPBearer(auto_error=False)


# ─── Token helpers ────────────────────────────────────────────────────────────

def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[str]:
    """Returns username from a valid token, or None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ─── Auth dependency ──────────────────────────────────────────────────────────

def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency — raises 401 if token is missing or invalid."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_token(credentials.credentials)
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


# ─── Credential validation ────────────────────────────────────────────────────

def validate_credentials(username: str, password: str) -> bool:
    """Returns True only if both username and password match the configured IBKR creds."""
    if not IBKR_USERNAME or not IBKR_PASSWORD:
        logger.error("IBKR_USERNAME / IBKR_PASSWORD env vars are not set — login is disabled.")
        return False
    # Use secrets.compare_digest() for timing-safe comparison to prevent
    # timing-oracle attacks that could reveal the correct credentials character-by-character.
    username_ok = secrets.compare_digest(username, IBKR_USERNAME)
    password_ok = secrets.compare_digest(password, IBKR_PASSWORD)
    return username_ok and password_ok
