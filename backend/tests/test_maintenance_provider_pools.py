"""HTTP pool reuse keeps credentials local to each synthetic request."""

from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx

from app.config import Settings
from app.services.google_oauth import GoogleOAuthClient
from app.services.storage import SupabaseStorage


def test_google_pool_binds_each_token_without_cookie_or_auth_carryover():
    captured = []

    def handler(request):
        captured.append((request.headers["Authorization"], request.headers.get("Cookie")))
        return httpx.Response(200, json={"items": []},
            headers={"Set-Cookie": "provider_session=synthetic; Path=/; Secure"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        oauth = GoogleOAuthClient(
            settings=Settings(_env_file=None, session_jwt_secret="x" * 32),
            http_client=client,
        )
        oauth.list_calendars("synthetic-A")
        oauth.list_calendars("synthetic-B")
        assert captured == [("Bearer synthetic-A", None), ("Bearer synthetic-B", None)]
        assert "Authorization" not in client.headers
        assert not list(client.cookies.jar)
        oauth.close()
        assert not client.is_closed


def test_storage_pool_keeps_service_credentials_on_each_request():
    captured = []

    def handler(request):
        captured.append((request.headers["Authorization"], request.headers.get("Cookie")))
        return httpx.Response(200, json=[],
            headers={"Set-Cookie": "storage_session=synthetic; Path=/; Secure"})

    with httpx.Client(transport=httpx.MockTransport(handler),
        cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))) as client:
        for key in ("synthetic-A", "synthetic-B"):
            storage = SupabaseStorage(settings=Settings(_env_file=None,
                session_jwt_secret="x" * 32, supabase_url="https://synthetic.invalid",
                supabase_service_role_key=key), http_client=client)
            assert storage.sign(["synthetic/path.png"]) == {}
            assert not client.is_closed
        assert captured == [("Bearer synthetic-A", None), ("Bearer synthetic-B", None)]
        assert "Authorization" not in client.headers
        assert not list(client.cookies.jar)
