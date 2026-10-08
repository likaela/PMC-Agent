"""Real HTTP acceptance of enterprise published catalogs (no mock, no publish)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.fact_repository import FactRepository
from repositories.fact_store import create_fact_store
from scripts.import_enterprise_boms import published_catalog, write_json


def validate_http(base_url: str, catalog: list[dict]) -> dict:
    checks = []

    def post(path, payload):
        request = Request(base_url.rstrip("/") + path,
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=90) as response:
            assert response.status == 200
            return json.loads(response.read().decode("utf-8"))

    def query(message):
        session = post("/api/v1/agent/sessions", {})
        payload = {"message": message, "session_id": session["session_id"]}
        result = post("/api/v1/agent/query", payload)
        assert result.get("scenario_id") is None, "企业请求不能进入 Demo"
        checks.append(dict(request=payload, response=result))
        return result

    products = query("有哪些已发布产品？")
    assert products["status"] == "ok"
    actual_codes = {row["product_code"] for row in products["structured_data"]["data"]["products"]}
    assert actual_codes == {entry["product"] for entry in catalog}
    assert products["provenance"]

    for entry in catalog:
        result = query(f"查询{entry['product']}的BOM")
        assert result["status"] == "ok"
        data = result["structured_data"]["data"]
        assert data["parent_item"]["material_code"] == entry["product"]
        assert data["revision"] == entry["revision"] and data["line_count"] == entry["line_count"]
        assert result["provenance"]["content_sha256"] == entry["provenance"]["content_sha256"]
        assert data["parent_item"]["unit"] is None
        assert all(line["unit"] is None and line["price"] is None for line in data["lines"])
        assert result["warnings"]
        refusal = query(f"生产100台{entry['product']}可以吗")
        assert refusal["status"] in {"needs_input", "data_unavailable"}
        unavailable = refusal["structured_data"].get("data")
        assert unavailable is None or unavailable.get("inventory_sufficient_for_requested") is None

    # Even supplying a query date does not assert an inventory quantity or unit.
    if any(entry["product"] == "KQ-Z112" for entry in catalog):
        refusal = query("生产100台KQ-Z112可以吗，使用V01，生效日期2025-03-18，截至2025-03-18T00:00:00+08:00")
        assert refusal["status"] == "data_unavailable"
        assert refusal["provenance"]
        assert any("单位" in warning for warning in refusal["warnings"])
    return dict(verified_at=datetime.now(UTC).isoformat(), mode="real_http_enterprise_no_mock",
                check_count=len(checks), checks=checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--report", type=Path, default=ROOT / "data/normalized/enterprise_bom_http_acceptance.json")
    args = parser.parse_args()
    catalog = published_catalog(FactRepository(create_fact_store()))
    if not catalog:
        raise ValueError("没有已发布企业 BOM，不能声称验收通过")
    report = validate_http(args.base_url, catalog)
    write_json(args.report, report)
    print(json.dumps(dict(check_count=report["check_count"], status="passed", products=[entry["product"] for entry in catalog]), ensure_ascii=False))


if __name__ == "__main__":
    main()
