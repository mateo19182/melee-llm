"""The public site: Access JWT checks, what visitors may queue, and which writes need the operator."""
import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from starlette.testclient import TestClient

from melee_llm.web import auth, jobs, server, specs

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEYS = {"k1": KEY.public_key()}
VISITOR = {"cf-connecting-ip": "203.0.113.7"}


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token(key=KEY, kid="k1", alg="RS256", **claims) -> str:
    now = time.time()
    body = {"aud": [auth.AUD], "iss": auth.TEAM, "exp": now + 3600, "nbf": now - 5, "email": "m@x", **claims}
    signing = f"{b64(json.dumps({'alg': alg, 'kid': kid}).encode())}.{b64(json.dumps(body).encode())}"
    return f"{signing}.{b64(key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256()))}"


def test_verify():
    assert auth.verify(token(), KEYS)["email"] == "m@x"
    assert auth.verify(token(aud=["someone-else"]), KEYS) is None
    assert auth.verify(token(iss="https://evil.cloudflareaccess.com"), KEYS) is None
    assert auth.verify(token(exp=time.time() - 1), KEYS) is None
    assert auth.verify(token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)), KEYS) is None
    assert auth.verify(token(kid="unknown"), KEYS) is None
    assert auth.verify(token(alg="none"), KEYS) is None
    head, body, sig = token().split(".")
    forged = b64(json.dumps({**json.loads(base64.urlsafe_b64decode(body + "==")), "email": "x@y"}).encode())
    assert auth.verify(f"{head}.{forged}.{sig}", KEYS) is None
    assert auth.verify("garbage", KEYS) is None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "team_keys", lambda refresh=False: KEYS)
    monkeypatch.setattr(specs, "llm_models", lambda: ["claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"])
    monkeypatch.setattr(jobs, "listing", lambda limit=100: [])
    monkeypatch.setattr(jobs, "set_setting", lambda *a: pytest.fail("a visitor changed a setting"))
    monkeypatch.setattr(jobs, "cancel", lambda *a: pytest.fail("a visitor cancelled a job"))
    monkeypatch.setattr(jobs, "setting", lambda key, default="": default)
    return TestClient(server.app)


def test_visitor_writes_refused(client):
    assert client.get("/api/me", headers=VISITOR).json() == {"admin": False}
    assert client.post("/api/settings", json={"arena": False}, headers=VISITOR).status_code == 403
    assert client.post("/api/jobs/1/cancel", headers=VISITOR).status_code == 403
    assert client.post("/api/live/listen", headers=VISITOR).status_code == 403
    assert client.get("/api/settings", headers=VISITOR).status_code == 200


def test_operator(client):
    assert client.get("/api/me").json() == {"admin": True}  # not through Cloudflare: this machine
    signed_in = {**VISITOR, "cookie": f"{auth.COOKIE}={token()}"}
    assert client.get("/api/me", headers=signed_in).json() == {"admin": True}
    forged = {**VISITOR, "cookie": f"{auth.COOKIE}={token(aud=['x'])}"}
    assert client.get("/api/me", headers=forged).json() == {"admin": False}


def test_login_keeps_the_access_token(client):
    r = client.get("/login?next=/launch", headers={**VISITOR, "cf-access-jwt-assertion": token()}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/launch"
    assert f"{auth.COOKIE}=" in r.headers["set-cookie"] and "HttpOnly" in r.headers["set-cookie"]
    r = client.get("/login?next=//evil.example", headers=VISITOR, follow_redirects=False)
    assert r.headers["location"] == "/" and "set-cookie" not in r.headers


def match(p1="llm_paused:claude-haiku-4-5-20251001", p2="cpu:5", games=1, **kw):
    return {"p1": p1, "p2": p2, "char1": "FOX", "char2": "FALCO", "stage": "BATTLEFIELD", "mode": "paused",
            "games": games, "dry_run": True, **kw}


def test_visitor_launch_limits(client, monkeypatch):
    post = lambda body, h=VISITOR: client.post("/api/jobs", json=body, headers=h)  # noqa: E731
    assert post(match()).status_code == 200
    assert post(match(p1="coach:sonnet,body=reyn", p2="shine")).status_code == 200
    for bad in (match(p1="llm_paused:claude-opus-5-5"), match(games=4), match(p1="jev_paused:jev-latest"),
                match(p1="llm_paused:claude-haiku-4-5-20251001,interval=1")):
        r = post(bad)
        assert r.status_code == 400 and r.json()["errors"], bad
    assert post(match(p1="llm_paused:claude-opus-5-5", games=10), {}).status_code == 200  # the operator, from this machine
    monkeypatch.setattr(jobs, "listing", lambda limit=100: [{"status": "queued"}] * specs.PUBLIC_QUEUE)
    assert "queue is full" in " ".join(post(match()).json()["errors"])


def test_public_catalog(client):
    cat = client.get("/api/catalog", headers=VISITOR).json()
    kinds = {k["kind"]: k for k in cat["kinds"]}
    assert "jev_paused" not in kinds and "coach_jev" not in kinds
    assert kinds["llm_paused"]["arg"]["options"] == ["claude-haiku-4-5-20251001", "claude-sonnet-5-5"]
    assert "random" in kinds["coach"]["arg"]["options"] and "options" not in kinds["coach"]
    assert cat["limits"]["games"] == specs.PUBLIC_GAMES
    assert "limits" not in client.get("/api/catalog").json()


def test_search_engine_pages():
    c = TestClient(server.app)
    assert '<link rel="canonical" href="https://melee.m19182.dev/bench">' in c.get("/bench").text
    assert '<meta property="og:url" content="https://melee.m19182.dev/">' in c.get("/live").text
    assert "Sitemap: https://melee.m19182.dev/sitemap.xml" in c.get("/robots.txt").text
    xml = c.get("/sitemap.xml").text
    for loc in ("/", "/bench", "/writeup/", "/docs/research"):
        assert f"<loc>https://melee.m19182.dev{loc}</loc>" in xml
    assert "/live<" not in xml and "/docs<" not in xml
