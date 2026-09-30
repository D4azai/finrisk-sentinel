"""Check browser OIDC behavior against intercepted provider responses, without an account."""

import argparse
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--channel", default=None)
    args = parser.parse_args()
    origin = args.url.rstrip("/")
    login = {
        "client_id": "smoke-client",
        "authorization_url": "https://login.example/authorize",
        "redirect_uri": origin + "/auth/callback",
        "issuer": "https://login.example",
        "scope": "openid finrisk:access",
        "audience": None,
    }
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel=args.channel)
        expect.set_options(timeout=20000)
        context = browser.new_context()
        page = context.new_page()
        errors, requests, exchanges = [], [], []
        behavior = {"mode": "success", "expires_in": 300}
        page.on("pageerror", lambda error: errors.append(str(error)))

        def api(route):
            path = urlsplit(route.request.url).path
            if path == "/v1/app-config":
                data = {
                    "browser_login": login,
                    "development_login": False,
                    "demo_data": False,
                    "paper_trading": False,
                    "live_trading": False,
                }
            elif path == "/v1/auth/exchange":
                body = route.request.post_data_json
                assert route.request.headers["origin"] == origin
                assert body["nonce"] == requests[-1]["nonce"][0]
                challenge = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(body["code_verifier"].encode()).digest()
                    )
                    .decode()
                    .rstrip("=")
                )
                assert challenge == requests[-1]["code_challenge"][0]
                assert body["code"] == "test-code"
                exchanges.append(body)
                data = {
                    "access_token": "in-memory-test-token",
                    "expires_in": behavior["expires_in"],
                }
            else:
                assert route.request.headers.get("authorization") == "Bearer in-memory-test-token"
                data = {"items": [], "next_cursor": None}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

        def authorize(route):
            params = parse_qs(urlsplit(route.request.url).query)
            requests.append(params)
            assert params["response_type"] == ["code"]
            assert params["code_challenge_method"] == ["S256"]
            assert params["redirect_uri"] == [login["redirect_uri"]]
            assert len(params["state"][0]) == len(params["nonce"][0]) == 43
            callback = {"state": params["state"][0], "code": "test-code", "iss": login["issuer"]}
            if behavior["mode"] == "mismatch":
                callback["state"] = "wrong-state"
            elif behavior["mode"] == "cancel":
                callback.pop("code")
                callback["error"] = "access_denied"
                callback["error_description"] = "untrusted-provider-detail"
            elif behavior["mode"] == "issuer":
                callback["iss"] = "https://other.example"
            query = urlencode(callback)
            if behavior["mode"] == "duplicate":
                query += "&code=second-code"
            route.fulfill(status=302, headers={"Location": login["redirect_uri"] + "?" + query})

        context.route(origin + "/v1/**", api)
        context.route("https://login.example/authorize**", authorize)

        def start():
            page.goto(origin, wait_until="networkidle")
            expect(page.locator("#login-form")).to_be_hidden()
            page.locator("#provider-login").click()

        start()
        expect(page.locator("#application")).to_be_visible()
        assert page.url == origin + "/"
        assert len(exchanges) == 1
        assert page.evaluate("sessionStorage.length === 0 && localStorage.length === 0")
        page.locator("#logout").click()
        expect(page.locator("#login-panel")).to_be_visible()
        assert page.evaluate("state.token === null")

        # Reusing a callback has no pending transaction and must not call exchange again.
        page.goto(
            login["redirect_uri"]
            + "?"
            + urlencode({"state": requests[-1]["state"][0], "code": "test-code"})
        )
        expect(page.locator("#notice")).to_contain_text("could not be verified")
        assert len(exchanges) == 1

        for mode in ("mismatch", "cancel", "issuer", "duplicate"):
            behavior["mode"] = mode
            start()
            expect(page.locator("#notice")).to_be_visible()
            expect(page.locator("#application")).to_be_hidden()
            assert "untrusted-provider-detail" not in page.locator("#notice").inner_text()
            assert page.url == origin + "/"
            assert page.evaluate("sessionStorage.length === 0")
            assert len(exchanges) == 1

        # A transaction beyond its ten-minute lifetime is rejected before exchanging.
        page.goto(origin, wait_until="networkidle")
        page.evaluate(
            """(config) => sessionStorage.setItem('finrisk.oidc.pending', JSON.stringify({
            state: 'expired-state', nonce: 'n'.repeat(43), verifier: 'v'.repeat(43),
            created: Date.now() - 601000, config: JSON.stringify(config)
        }))""",
            login,
        )
        page.goto(login["redirect_uri"] + "?state=expired-state&code=test-code")
        expect(page.locator("#notice")).to_contain_text("expired")
        assert len(exchanges) == 1

        behavior.update(mode="success", expires_in=1)
        start()
        expect(page.locator("#application")).to_be_visible()
        expect(page.locator("#notice")).to_contain_text("Your session expired")
        expect(page.locator("#login-panel")).to_be_visible()
        assert page.evaluate("state.token === null")
        assert not errors, errors
        browser.close()
    print(
        "PASS: PKCE, callback state/issuer, cancellation, replay/expiry rejection, memory-only token and sign-out."
    )
    print("Provider/API responses were intercepted; no external identity account was used.")


if __name__ == "__main__":
    main()
