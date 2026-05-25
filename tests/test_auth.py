"""Tests for auth token store."""
import time
from src.api.auth import TokenStore


class TestTokenStore:
    def setup_method(self):
        self.store = TokenStore(access_ttl=3600, refresh_ttl=86400)

    def test_create_session_returns_tokens(self):
        result = self.store.create_session("alice", "admin")
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["token_type"] == "bearer"
        assert result["expires_in"] == 3600

    def test_validate_valid_access_token(self):
        session = self.store.create_session("alice", "admin")
        claims = self.store.validate_access_token(session["access_token"])
        assert claims is not None
        assert claims["user"] == "alice"
        assert claims["role"] == "admin"

    def test_validate_invalid_token_returns_none(self):
        assert self.store.validate_access_token("invalid-token") is None

    def test_validate_expired_token_returns_none(self):
        short_store = TokenStore(access_ttl=0, refresh_ttl=86400)
        session = short_store.create_session("alice", "admin")
        time.sleep(0.001)
        assert short_store.validate_access_token(session["access_token"]) is None

    def test_refresh_token_rotation(self):
        session = self.store.create_session("alice", "admin")
        old_refresh = session["refresh_token"]
        new_session = self.store.refresh(old_refresh)
        assert new_session is not None
        assert new_session["access_token"] != session["access_token"]
        assert new_session["refresh_token"] != old_refresh
        assert self.store.refresh(old_refresh) is None

    def test_refresh_invalid_token_returns_none(self):
        assert self.store.refresh("invalid-token") is None

    def test_revoke_session_invalidates_all_tokens(self):
        session = self.store.create_session("alice", "admin")
        claims = self.store.validate_access_token(session["access_token"])
        session_id = claims["session_id"]
        self.store.revoke_session(session_id)
        assert self.store.validate_access_token(session["access_token"]) is None
        assert self.store.refresh(session["refresh_token"]) is None
