"""Exercise the local application in a real browser; creates a separate demo workspace."""

import argparse
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--channel", default=None, help="Installed browser channel, e.g. msedge")
    parser.add_argument("--screenshots-dir", type=Path, default=Path(".artifacts"))
    args = parser.parse_args()
    args.screenshots_dir = args.screenshots_dir.resolve()
    args.screenshots_dir.mkdir(parents=True, exist_ok=True)
    print("Starting browser runtime...", flush=True)
    with sync_playwright() as p:
        print("Launching browser...", flush=True)
        browser = p.chromium.launch(headless=True, channel=args.channel, timeout=30000)
        expect.set_options(timeout=20000)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until="networkidle")
        print("Dashboard loaded; exercising application...", flush=True)
        expect(page.locator("#landing")).to_be_visible()
        expect(page.locator(".landing-hero h1")).to_contain_text("Know what you own")
        expect(page.locator("#app-shell")).to_be_hidden()
        page.screenshot(path=str(args.screenshots_dir / "landing-desktop.png"), full_page=True)
        page.locator("#login-form button").click()
        expect(page.locator("#application")).to_be_visible()
        expect(page.locator(".instrument-button").first).to_be_visible()
        page.locator("#command-search").click()
        expect(page.locator("#search")).to_be_focused()
        page.locator('.nav[data-view="overview"]').click()
        providers = page.evaluate("api('/v1/market-data/providers')")
        assert providers["live_provider_configured"] is False
        assert any(s["source"] == "finrisk-demo-v1" for s in providers["stored_daily_sources"])
        page.locator("#workspace-name").fill("Browser demo " + uuid4().hex[:8])
        page.locator("#workspace-form button").click()
        expect(page.locator("#workspace-name")).to_have_value("")
        expect(page.locator("#sample-portfolio")).to_be_enabled()
        expect(page.locator("#position-count")).to_have_text("—")
        page.locator("#sample-portfolio").click()
        expect(page.locator("#position-count")).to_have_text("3", timeout=30000)
        expect(page.locator("#allocation-legend > span")).to_have_count(3)
        expect(page.locator("#valuation-status")).to_contain_text("DEMO")
        expect(page.locator("#risk-lab-status")).to_have_text("LIMITED", timeout=30000)
        expect(page.locator("#risk-es")).not_to_have_text("â€”")
        expect(page.locator("#risk-scenarios tr")).to_have_count(4)
        expect(page.locator("#risk-attribution tr")).to_have_count(3)
        page.locator("#save-risk-snapshot").click()
        expect(page.locator("#risk-snapshot-status")).to_contain_text("Saved risk evidence")
        page.locator("#save-snapshot").click()
        expect(page.locator("#snapshot-status")).to_contain_text("Saved valuation")
        page.locator(".instrument-button").filter(has_text="DEMO-SPIKE").click()
        expect(page.locator("#signal-summary")).to_have_text("Elevated")
        page.locator('[data-chart-range="22"]').click()
        expect(page.locator('[data-chart-range="22"]')).to_have_class("active")
        page.locator('[data-chart-range="61"]').click()
        page.locator("#watch-instrument").click()
        page.locator('.nav[data-view="alerts"]').click()
        expect(page.locator("#watchlist tr")).to_have_count(1)
        page.locator("#run-risk-scan").click()
        expect(page.locator("#open-alert-count")).to_have_text("1 open")
        expect(page.locator("#risk-alerts tr")).to_have_count(1)
        page.locator("#risk-alerts button").click()
        expect(page.locator("#open-alert-count")).to_have_text("0 open")
        page.screenshot(path=str(args.screenshots_dir / "dashboard-alerts.png"), full_page=True)
        page.locator('.nav[data-view="paper"]').click()
        page.locator("#account-form button").click()
        expect(page.locator("#paper-cash")).to_contain_text("100,000")
        page.screenshot(
            path=str(args.screenshots_dir / "dashboard-paper-trading.png"),
            full_page=True,
        )
        page.locator("#order-quantity").fill("2")
        page.locator("#order-submit").click()
        expect(page.locator("#order-result")).to_contain_text("FILLED")
        expect(page.locator("#orders tr")).to_have_count(1)
        page.locator("#order-side").select_option("sell")
        page.locator("#order-submit").click()
        expect(page.locator("#orders tr")).to_have_count(2)
        expect(page.locator("#paper-cash")).to_contain_text("100,000")
        page.locator('.nav[data-view="overview"]').click()
        expect(page.locator("#portfolio")).to_be_visible()
        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
        page.wait_for_function("scrollY === 0")
        page.screenshot(path=str(args.screenshots_dir / "dashboard-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(args.screenshots_dir / "dashboard-mobile.png"), full_page=True)
        overflow = page.evaluate(
            """[...document.querySelectorAll('*')]
            .filter(e => { const r=e.getBoundingClientRect(); return r.right>innerWidth+1 || r.left < -1; })
            .slice(0,10).map(e => `${e.tagName.toLowerCase()}#${e.id}.${e.className} ${Math.round(e.getBoundingClientRect().right)}`)"""
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
            f"Mobile horizontal overflow: {overflow}"
        )
        expect(page.locator("#notice")).to_be_hidden()
        page.locator("#logout").click()
        expect(page.locator("#login-panel")).to_be_visible()
        expect(page.locator("#landing")).to_be_visible()
        expect(page.locator("#app-shell")).to_be_hidden()
        page.screenshot(path=str(args.screenshots_dir / "landing-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print(
        "PASS: browser login, workspace, portfolio, risk alert, paper buy/sell, logout and mobile layout."
    )
    print("Demo workspace, portfolio and paper audit records are retained for inspection.")


if __name__ == "__main__":
    main()
