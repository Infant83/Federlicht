from federlicht import report
from federlicht.site_hub_index import build_site_index_html


def test_build_site_index_html_embeds_manifest_and_refresh_interval() -> None:
    manifest = {
        "revision": "rev-1",
        "generated_at": "2026-02-09T12:00:00",
        "items": [
            {
                "title": "Sample",
                "summary": "Summary",
                "paths": {"report": "runs/sample/report_full.html"},
            }
        ],
    }
    html = build_site_index_html(manifest, refresh_minutes=3)
    assert '<script id="manifest-data" type="application/json">' in html
    assert '"revision": "rev-1"' in html
    assert "const REFRESH_MS = 180000;" in html


def test_report_wrapper_uses_site_hub_index_renderer() -> None:
    manifest = {
        "revision": "rev-2",
        "generated_at": "2026-02-09T12:00:00",
        "items": [{"title": "</script><script>alert(1)</script>"}],
    }
    direct = build_site_index_html(manifest, refresh_minutes=1)
    via_report = report.build_site_index_html(manifest, refresh_minutes=1)
    assert via_report == direct
    assert "<\\/script>" in via_report
