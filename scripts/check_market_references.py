"""Exercise daily FX fallback and withholding premium for invalid/missing inputs."""

import json

from playwright.sync_api import sync_playwright

from check_live_widget import MarketFixture, cleanup, install_quote_transport, widget_html


def verify(browser, name, settings, ready):
    page = browser.new_page(viewport={"width": 390, "height": 362})
    page.clock.install()
    install_quote_transport(page)
    fixture = MarketFixture(page)
    for key, value in settings.items():
        setattr(fixture, key, value)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("http://widget.test/", lambda r: r.fulfill(body=widget_html(), content_type="text/html"))
    page.goto("http://widget.test/")
    page.locator("#ethereum .price span").get_by_text("3,000.25", exact=True).wait_for()
    page.wait_for_timeout(150)
    page.clock.run_for(500)
    assert page.locator("#premium").get_attribute("data-ready") == str(ready).lower(), name
    if ready:
        assert page.locator("#premium .price span").inner_text() == "+2.00"
        assert "ECB 일별" in page.locator("#forex .change").inner_text()
        assert "일별 환율 기반" in page.locator("#premium .status").inner_text()
    else:
        assert page.locator("#premium .price span").inner_text() == "—"
    if name == "missing_fx":
        fixture.fx_fail = fixture.fallback_fail = False
        with page.expect_response(lambda r: "forex/recent" in r.url and r.status == 200):
            page.clock.fast_forward(61000)
        page.wait_for_timeout(150)
        page.clock.run_for(500)
        assert page.locator("#premium").get_attribute("data-ready") == "true", (
            "Recovered FX did not restore premium"
        )
    assert not errors, errors
    cleanup(page, page.main_frame)
    return {"case": name, "passed": True}


if __name__ == "__main__":
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        cases = [
            ("daily_fallback", {"fx_fail": True, "fx_age_days": 2}, True),
            ("missing_fx", {"fx_fail": True, "fallback_fail": True}, False),
            ("missing_peg", {"peg_fail": True}, False),
            ("old_fx", {"fx_age_days": 5}, False),
            ("old_peg", {"peg_age_ms": 301000}, False),
            ("zero_fx", {"fx_price": 0}, False),
            ("invalid_peg", {"peg_price": -1}, False),
        ]
        print(json.dumps([verify(browser, *case) for case in cases]))
        browser.close()
