from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "website/dist"
TOKEN = "4df5daad98934fc184b2f3f580d98832"


def test_cookie_free_analytics_on_every_page():
    pages = sorted(DIST.glob("*.html"))
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        # Google Search Console's verification page is deliberately HTML-only.
        if page.name.startswith("google") and page.name.endswith(".html"):
            continue
        assert html.count("https://static.cloudflareinsights.com/beacon.min.js") == 1, page.name
        assert f'"token":"{TOKEN}"' in html, page.name
        assert "type=\"module\"" in html, page.name
        assert "analytics-consent.js" not in html, page.name
        assert "cookiePreferences" not in html, page.name
        assert "googletagmanager.com/gtag" not in html, page.name
        assert "google-analytics.com" not in html, page.name


def test_privacy_notice_describes_current_analytics():
    privacy = (DIST / "privacy.html").read_text(encoding="utf-8")
    assert "Cloudflare Web Analytics" in privacy
    assert "does not use analytics cookies" in privacy
    assert "cloudflareinsights.com" in privacy
    assert "romi@lens.unifi.it" in privacy
    assert not (DIST / "analytics-consent.js").exists()
