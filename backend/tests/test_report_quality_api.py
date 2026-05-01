from __future__ import annotations


def test_report_claims_and_quality_api_return_404_for_missing_report(client):
    claims = client.get("/api/reports/not-a-real-report/claims")
    quality = client.get("/api/reports/not-a-real-report/quality")

    assert claims.status_code == 404
    assert quality.status_code == 404
