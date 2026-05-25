"""Run auth token store tests directly (bypasses import chain issues on Windows)."""
import sys
import time

# Test TokenStore directly by importing just the file
sys.path.insert(0, "D:/AI/AgentOrchestration/src/api")

import importlib.util
spec = importlib.util.spec_from_file_location("auth", "D:/AI/AgentOrchestration/src/api/auth.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)

TokenStore = auth.TokenStore

passed = 0
failed = 0

def test(name, ok):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}")

print("=== Auth Token Store Tests ===\n")

# Setup
store = TokenStore(access_ttl=3600, refresh_ttl=86400)

# Test create session
session = store.create_session("alice", "admin")
test("create_session returns access_token", "access_token" in session)
test("create_session returns refresh_token", "refresh_token" in session)
test("create_session token_type is bearer", session["token_type"] == "bearer")
test("create_session expires_in is 3600", session["expires_in"] == 3600)

# Test validate access token
claims = store.validate_access_token(session["access_token"])
test("validate valid token returns claims", claims is not None)
test("validate claims user is alice", claims and claims["user"] == "alice")
test("validate claims role is admin", claims and claims["role"] == "admin")

# Test invalid token
test("validate invalid token returns None", store.validate_access_token("bad-token") is None)

# Test expired token
short = TokenStore(access_ttl=0, refresh_ttl=86400)
expired_session = short.create_session("bob", "user")
time.sleep(0.001)
test("validate expired token returns None", short.validate_access_token(expired_session["access_token"]) is None)

# Test refresh token rotation
s1 = store.create_session("carol", "user")
old_refresh = s1["refresh_token"]
s2 = store.refresh(old_refresh)
test("refresh returns new session", s2 is not None)
test("refresh returns new access_token", s2 and s2["access_token"] != s1["access_token"])
test("refresh returns new refresh_token", s2 and s2["refresh_token"] != old_refresh)
test("old refresh token invalidated (rotation)", store.refresh(old_refresh) is None)

# Test invalid refresh
test("refresh invalid token returns None", store.refresh("bad-token") is None)

# Test revoke session
s3 = store.create_session("dave", "admin")
c3 = store.validate_access_token(s3["access_token"])
store.revoke_session(c3["session_id"])
test("revoke invalidates access token", store.validate_access_token(s3["access_token"]) is None)
test("revoke invalidates refresh token", store.refresh(s3["refresh_token"]) is None)

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
