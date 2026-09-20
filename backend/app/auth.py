"""Real auth: salted PBKDF2 passwords, bearer tokens, roles. First account is admin. Admins may preview other roles.

Storage goes through the active FactRepository (SQLite locally, DynamoDB on AWS), so the
same code runs on a laptop and on Lambda with no local database file.
"""
import hashlib, hmac, json, secrets

from fastapi import Depends, Header, HTTPException

from .factory import get_fact_repository


def _hash(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 120_000).hex()


def _issue(user, role):
    tok = secrets.token_urlsafe(32)
    get_fact_repository().create_token(tok, user)
    return {"token": tok, "user": user, "role": role}


def register(user, pw):
    repo = get_fact_repository()
    if not user or len(pw) < 6:
        raise HTTPException(422, "Pick a username and a password of at least 6 characters")
    if repo.get_user(user):
        raise HTTPException(409, "That username is taken")
    role = "member" if repo.has_any_user() else "admin"
    salt = secrets.token_bytes(16)
    repo.create_user(user, salt.hex() + "$" + _hash(pw, salt), role)
    return _issue(user, role)


def login(user, pw):
    r = get_fact_repository().get_user(user)
    if r:
        salt, h = r["pw"].split("$")
        if hmac.compare_digest(h, _hash(pw, bytes.fromhex(salt))):
            return _issue(user, r["role"])
    raise HTTPException(401, "Wrong username or password")


def current(authorization: str = Header(""), x_view_as: str = Header("")):
    repo = get_fact_repository()
    u = repo.get_token_user(authorization.removeprefix("Bearer ").strip())
    if not u:
        raise HTTPException(401, "Sign in required")
    user, role = u["username"], u["role"]
    view = x_view_as or role
    if view != role and role != "admin":
        raise HTTPException(403, "Only admins can preview other roles")
    tags = repo.get_role_tags(view)
    if tags is None:
        raise HTTPException(403, f"Unknown role '{view}'")
    return {"user": user, "role": role, "view": view, "allowed": tags}


def require_admin(c=Depends(current)):
    if c["role"] != "admin":
        raise HTTPException(403, "Admin role required")
    return c


def is_visible(fact_tags: list[str] | set[str] | str | None, allowed: list[str] | set[str] | None) -> bool:
    """Single global RBAC visibility function with explicit, strict semantics.

    Semantics:
    1. Super-admin wildcard ('*'): If '*' in allowed, always returns True.
    2. Empty / Public fact tags: If fact has no tags or empty tags (or only default 'general'),
       it is public to all authenticated users -> returns True.
    3. Restricted tags: All domain-restricted tags associated with the fact (excluding default 'general')
       must be present in the caller's allowed tags (i.e. domain_tags.issubset(set(allowed))).
       A fact with tags ['frontend', 'secret'] requires the caller to hold BOTH 'frontend' AND 'secret' permissions.
    """
    if allowed is None:
        return False
    if "*" in allowed:
        return True
    if fact_tags is None:
        return True
    if isinstance(fact_tags, str):
        try:
            tags_set = set(json.loads(fact_tags))
        except Exception:
            tags_set = {fact_tags} if fact_tags.strip() else set()
    elif isinstance(fact_tags, (list, set, tuple)):
        tags_set = set(fact_tags)
    else:
        tags_set = set()

    # Domain tags require explicit clearance (excluding fallback 'general' tag)
    domain_tags = tags_set - {"general"}
    if not domain_tags:
        return True
    return domain_tags.issubset(set(allowed))


def can_access_project(user: str, role: str, project: dict | None) -> bool:
    """Check if user/role has permission to access the specified project."""
    if not project:
        return False
    if role == "admin":
        return True
    if project.get("created_by") == user:
        return True
    members_raw = project.get("members", '["*"]')
    if isinstance(members_raw, str):
        try:
            members = json.loads(members_raw)
        except Exception:
            members = [members_raw]
    else:
        members = list(members_raw or [])
    if "*" in members or user in members or role in members:
        return True
    return False
