"""Materialize the approved set without re-filtering; backup before any writes."""
import argparse
import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.slim_review_service import load_dataset
from repositories.current_business_repository import CurrentBusinessRepository


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(dataset_path, output_root, *, archive_paths=()):
    d = load_dataset(dataset_path)
    if d["synthetic"]:
        raise ValueError("Current business source requires verified non-synthetic stock")
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    root = Path(output_root).resolve() / version
    if not root.is_relative_to(ROOT):
        raise ValueError("Working source must stay inside project")
    root.mkdir(parents=True, exist_ok=False)
    backup = root / "private_archive"
    backup.mkdir()
    audit = []
    for index, path in enumerate([Path(dataset_path), *map(Path, archive_paths)]):
        path = path.resolve(strict=True)
        target = backup / f"{index:02d}-{path.name}"
        shutil.copy2(path, target)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Archive integrity failure")
        audit.append(dict(original_path=str(path), archive_path=target.name, sha256=digest))
    revision = d["revision"] + "-C" + str(len(d["bom"]["data"]["lines"]))
    bom = copy.deepcopy(d["bom"])
    bom["query"].update(revision=revision)
    bom["data"]["revision"] = revision
    for index, line in enumerate(bom["data"]["lines"], 1):
        line["provenance"] = dict(source_file="bom.json", sheet_name="current_bom", row_number=index, dataset_version=version)
    bom["provenance"] = dict(bom_version=revision, source_file="bom.json", dataset_version=version, source_kind="versioned_business_configuration")
    stocks = copy.deepcopy(d["observations"])
    codes = {r["child_item"]["material_code"] for r in bom["data"]["lines"]}
    stocks["source_file"] = "inventory.json"
    stocks["records"] = {code: rows for code, rows in stocks["records"].items() if code in codes}
    stocks["record_count"] = sum(len(rows) for rows in stocks["records"].values())
    stocks["unique_material_count"] = len(stocks["records"])
    stocks["duplicate_observation_count"] = 0
    original_confirmation = copy.deepcopy(stocks["quantity_confirmation"])
    original_confirmation["product_scope"] = [dict(product=d["product"], revision=revision)]
    original_confirmation.update(source_file="inventory.json", source_uri=None,
        source_kind="confirmed_working_copy", confirmation_id="current-" + version,
        quantity_field="recorded_stock_qty", recorded_at=datetime.now(timezone.utc).isoformat(),
        reason="Approved current business configuration; identical verified source quantities")
    stocks["quantity_confirmation"] = original_confirmation
    lineage = []
    working_row = 0
    for code, rows in stocks["records"].items():
        for row in rows:
            working_row += 1
            lineage.append(dict(material_code=code, working_row_number=working_row, original_provenance=copy.deepcopy(row["provenance"])))
            row["provenance"] = dict(source_file="inventory.json", sheet_name="current_inventory", row_number=working_row, dataset_version=version)
    stocks["row_errors"] = []
    stocks["excluded_sheets"] = []
    # Embedded original confirmations remain as private audit only, not stale active hashes.
    stocks.pop("content_sha256", None)
    stocks["quantity_confirmation"].pop("content_sha256", None)
    stocks["unit_confirmation"] = dict(unit=bom["data"]["parent_item"]["unit"], source_kind="confirmed_working_copy")
    aliases = {code: alias for code, alias in d["material_aliases"].items() if code in codes}
    files = {}
    for key, value in dict(bom=bom, inventory=stocks, aliases=aliases).items():
        filename = key + ".json"
        files[key] = dict(path=filename, sha256=write_json(root / filename, value))
    manifest = dict(format="current_business_bom_v1", dataset_version=version, product=d["product"], revision=revision,
        source_revision=d["revision"], material_count=len(codes), synthetic=False, files=files,
        confirmations={k: dict(content_sha256=files[k]["sha256"], unit=bom["data"]["parent_item"]["unit"],
            source="existing_human_confirmation_and_current_configuration_authorization") for k in ("bom", "inventory")},
        provenance=dict(parent_dataset_version=d["dataset_version"], parent_sha256=d["dataset_sha256"]))
    write_json(root / "manifest.json", manifest)
    write_json(root / "private_audit.json", dict(archives=audit, original_bom_provenance=d["bom"]["provenance"],
        original_observations=d["observations"], original_confirmation=d["observations"]["quantity_confirmation"],
        inventory_lineage=lineage, excluded=d["excluded"]))
    CurrentBusinessRepository(root / "manifest.json")  # Same reader used by production.
    return root / "manifest.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "data/normalized/current_business")
    parser.add_argument("--archive", type=Path, action="append", default=[])
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    manifest = prepare(args.dataset, args.output_root, archive_paths=args.archive)
    if args.activate:
        profile = ROOT / "data/facts/confirmations/current_business.json"
        if profile.exists():
            shutil.copy2(profile, manifest.parent / "private_archive/previous_current_business.json")
        write_json(profile, dict(manifest_path=str(manifest.relative_to(ROOT))))
    print(json.dumps(dict(manifest_path=str(manifest.relative_to(ROOT))), ensure_ascii=False))
