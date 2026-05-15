"""Playwright tests for the ⟨ψ⟩Quantum benchmark dashboard.

Requires the dashboard HTML to exist at reports/benchmark_dashboard.html.
Run: C:\\G\\python.exe tools/bench_dashboard.py  (generates the HTML)
Then: C:\\G\\python.exe -m pytest tests/test_benchmark_dashboard_playwright.py -v

Set PLAYWRIGHT_ENABLED=1 to enable: $env:PLAYWRIGHT_ENABLED=1
"""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "reports" / "benchmark_dashboard.html"
DASHBOARD_URL = DASHBOARD_PATH.as_uri() if DASHBOARD_PATH.exists() else ""

pytestmark = pytest.mark.playwright


@pytest.fixture(scope="module")
def browser():
    """Launch a Chromium browser for the test module."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser):
    """Open the dashboard in a new browser page."""
    p = browser.new_page()
    yield p
    p.close()


@pytest.mark.skipif(not DASHBOARD_PATH.exists(), reason="Dashboard HTML not generated — run bench_dashboard.py first")
def test_dashboard_loads(page):
    """Benchmark dashboard loads without JS errors."""
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(DASHBOARD_URL)
    assert page.title() != "", "Page title should not be empty"
    assert errors == [], f"JS errors on page load: {errors}"


@pytest.mark.skipif(not DASHBOARD_PATH.exists(), reason="Dashboard HTML not generated — run bench_dashboard.py first")
def test_dashboard_has_benchmark_content(page):
    """Dashboard renders benchmark content."""
    page.goto(DASHBOARD_URL)
    body_text = page.inner_text("body")
    assert len(body_text.strip()) > 50, "Dashboard body appears empty"
