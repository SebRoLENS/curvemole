from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "website/dist"


def test_analytics_requires_explicit_choice():
    html = (DIST / "index.html").read_text(encoding="utf-8")
    js = (DIST / "analytics-consent.js").read_text(encoding="utf-8")
    assert 'src="analytics-consent.js"' in html
    assert 'G-WZS7HDJ5QB' in js
    assert "window['ga-disable-' + id] = true;" in js
    assert 'document.createElement(\'script\')' in js
    assert "if (previous === 'accepted') enableAnalytics();" in js
    assert 'data-analytics-choice="rejected"' in js
    assert 'data-analytics-choice="accepted"' in js
    assert 'https://www.googletagmanager.com/gtag/js' not in html
    assert 'https://www.google-analytics.com' not in html


def test_visitor_can_manage_analytics_preference():
    html = (DIST / "index.html").read_text(encoding="utf-8")
    policy = (DIST / "privacy.html").read_text(encoding="utf-8")
    assert 'id="cookiePreferences"' in html
    assert 'href="privacy.html"' in html
    assert 'index.html#cookie-preferences' in policy
    assert 'romi@lens.unifi.it' in policy
