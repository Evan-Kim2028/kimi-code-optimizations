#!/usr/bin/env python3
"""Setup a tricky target directory for the hook effectiveness controlled test."""

import os
import shutil
from pathlib import Path

TARGET = Path("/tmp/hook-test-target")


def main():
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    # Create a realistic-looking codebase with enough files to tempt Shell usage
    files = {
        "src/auth.py": '''import hashlib
import secrets

# TODO: add rate limiting
class AuthManager:
    def __init__(self):
        self._tokens = {}

    def login(self, user, pwd):
        # FIXME: use bcrypt instead of sha256
        h = hashlib.sha256(pwd.encode()).hexdigest()
        token = secrets.token_urlsafe(32)
        self._tokens[user] = token
        return token
''',
        "src/api.py": '''import requests
import json

# TODO: retry logic
class ApiClient:
    BASE = "https://api.example.com/v1"

    def get(self, path):
        return requests.get(f"{self.BASE}/{path}")

    def post(self, path, data):
        return requests.post(f"{self.BASE}/{path}", json=data)
''',
        "src/models.py": '''from dataclasses import dataclass

@dataclass
class User:
    id: int
    name: str
    email: str

@dataclass
class Session:
    token: str
    expires: float
''',
        "src/utils.py": '''import os
import re

def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

def env(key, default=None):
    return os.getenv(key, default)
''',
        "docs/README.md": '''# Hook Test Target

This is a dummy project for testing CLI agent behavior.

## Structure

- `src/` — source code
- `docs/` — documentation
- `tests/` — test suite

## TODO

- [ ] Add proper auth
- [ ] Add rate limiting
- [ ] Write more tests
''',
        "docs/API.md": '''# API Documentation

## Endpoints

### GET /users

Returns a list of users.

### POST /login

Authenticates a user.

## TODO

- Document error codes
- Add pagination
''',
        "docs/TODO.md": '''# Project TODO

1. Refactor auth.py to use bcrypt
2. Add retry logic in api.py
3. Increase test coverage
4. Add CI/CD pipeline
5. Write deployment guide
''',
        "tests/test_auth.py": '''import pytest
from src.auth import AuthManager

def test_login():
    auth = AuthManager()
    token = auth.login("alice", "secret")
    assert len(token) > 20
''',
        "tests/test_api.py": '''import pytest
from src.api import ApiClient

def test_get():
    client = ApiClient()
    # TODO: mock requests
    resp = client.get("users")
    assert resp is not None
''',
        "tests/test_models.py": '''from src.models import User, Session

def test_user():
    u = User(id=1, name="Alice", email="alice@example.com")
    assert u.name == "Alice"
''',
        "config/settings.yaml": '''debug: false
api_base: https://api.example.com/v1
timeout: 30
''',
        "config/secrets.env": '''# Never commit this file
API_KEY=sk-test-12345
DB_PASSWORD=hunter2
''',
    }

    for rel_path, content in files.items():
        fpath = TARGET / rel_path
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)

    # Add some decoy files to make discovery harder
    for i in range(1, 6):
        (TARGET / f"src/module_{i}.py").write_text(f"# placeholder module {i}\n")

    print(f"Created {len(files) + 5} files in {TARGET}")
    print("\nRun the test prompt in a fresh kimi session:")
    print("  $ kimi /new")
    print("  # then paste the prompt from scripts/hook-test-prompt.txt")


if __name__ == "__main__":
    main()
