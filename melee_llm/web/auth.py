"""Who may change things: the site is public, the operator signs in through Cloudflare Access.

Access protects only /login on melee.m19182.dev. Signing in there hands the server an Access JWT, which it keeps in
its own cookie and checks (RS256 against the team's published keys, audience, expiry) on every request. Requests
that did not come through Cloudflare (no Cf-Connecting-Ip: scripts and tools on this machine) count as the operator.
"""
from __future__ import annotations

import base64
import json
import os
import time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from starlette.requests import HTTPConnection

TEAM = os.environ.get("MELEE_ACCESS_TEAM", "https://m19182.cloudflareaccess.com")
AUD = os.environ.get("MELEE_ACCESS_AUD", "4b2c1ad93ca93bdc9a0f78a10b486e9dbf80a84309694ab6b35dfcb77cd6eb6e")
COOKIE = "melee_admin"

_keys: tuple[float, dict] = (0.0, {})


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _int(s: str) -> int:
    return int.from_bytes(_b64(s), "big")


def team_keys(refresh: bool = False) -> dict[str, rsa.RSAPublicKey]:
    """kid → public key, cached an hour (Access rotates keys every few weeks and publishes the next one early)."""
    global _keys
    age = time.time() - _keys[0]
    if age > 3600 or (refresh and age > 60):
        try:
            jwks = httpx.get(f"{TEAM}/cdn-cgi/access/certs", timeout=5).json()["keys"]
            _keys = (time.time(), {k["kid"]: rsa.RSAPublicNumbers(_int(k["e"]), _int(k["n"])).public_key()
                                   for k in jwks if k.get("kty") == "RSA"})
        except (httpx.HTTPError, ValueError, KeyError):
            _keys = (time.time() - 3300, _keys[1])  # retry in 5 minutes, keep the old keys meanwhile
    return _keys[1]


def verify(token: str, keys=None) -> dict | None:
    """The token's claims if it is a valid, unexpired Access JWT for this application, else None."""
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        head, claims = json.loads(_b64(head_b64)), json.loads(_b64(body_b64))
    except ValueError:
        return None
    if head.get("alg") != "RS256":
        return None
    key = (keys if keys is not None else team_keys()).get(head.get("kid"))
    if key is None and keys is None:
        key = team_keys(refresh=True).get(head.get("kid"))  # a key published since the last fetch
    if key is None:
        return None
    try:
        key.verify(_b64(sig_b64), f"{head_b64}.{body_b64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError):
        return None
    aud = claims.get("aud")
    if AUD not in (aud if isinstance(aud, list) else [aud]) or claims.get("iss") != TEAM:
        return None
    if not claims.get("exp", 0) > time.time() >= claims.get("nbf", 0) - 60:
        return None
    return claims


def access_token(conn: HTTPConnection) -> str | None:
    return conn.headers.get("cf-access-jwt-assertion") or conn.cookies.get(COOKIE) or conn.cookies.get("CF_Authorization")


def is_admin(conn: HTTPConnection) -> bool:
    if "cf-connecting-ip" not in conn.headers:
        return True
    token = access_token(conn)
    return bool(token and verify(token))
