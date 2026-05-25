"""In-memory token store with refresh token rotation."""

import time
import secrets
from typing import Dict, Optional


class TokenStore:
    """Simple in-memory token store with refresh token rotation.

    Maps session IDs to active access tokens. Access tokens are short-lived;
    refresh tokens can be exchanged once for a new access + refresh pair
    (rotation), invalidating the old refresh token.
    """

    def __init__(self, access_ttl: int = 3600, refresh_ttl: int = 86400):
        self._access_tokens: Dict[str, dict] = {}
        self._refresh_tokens: Dict[str, dict] = {}
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

    def create_session(self, user: str, role: str = "user") -> Dict:
        """Create a new access + refresh token pair for a user."""
        session_id = secrets.token_hex(16)
        access_token = secrets.token_hex(32)
        refresh_token = secrets.token_hex(32)
        now = time.time()

        self._access_tokens[access_token] = {
            "session_id": session_id,
            "user": user,
            "role": role,
            "expires": now + self._access_ttl,
        }
        self._refresh_tokens[refresh_token] = {
            "session_id": session_id,
            "user": user,
            "role": role,
            "expires": now + self._refresh_ttl,
        }

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self._access_ttl,
        }

    def validate_access_token(self, token: str) -> Optional[Dict]:
        """Validate an access token and return its claims, or None."""
        data = self._access_tokens.get(token)
        if not data:
            return None
        if time.time() > data["expires"]:
            self._access_tokens.pop(token, None)
            return None
        return {"session_id": data["session_id"], "user": data["user"], "role": data["role"]}

    def refresh(self, refresh_token: str) -> Optional[Dict]:
        """Exchange a refresh token for a new access + refresh pair (rotation).

        The old refresh token is invalidated after use.
        Returns None if the refresh token is invalid or expired.
        """
        data = self._refresh_tokens.pop(refresh_token, None)
        if not data:
            return None
        if time.time() > data["expires"]:
            return None
        return self.create_session(data["user"], data["role"])

    def revoke_session(self, session_id: str) -> None:
        """Revoke all tokens for a session."""
        to_remove_access = [
            k for k, v in self._access_tokens.items()
            if v["session_id"] == session_id
        ]
        for k in to_remove_access:
            self._access_tokens.pop(k, None)

        to_remove_refresh = [
            k for k, v in self._refresh_tokens.items()
            if v["session_id"] == session_id
        ]
        for k in to_remove_refresh:
            self._refresh_tokens.pop(k, None)
