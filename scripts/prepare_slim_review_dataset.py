"""Back up sources, then create private versioned filtered review JSON datasets.

No migration, publishing, Excel modification or LLM use. Generated material
details and backups remain under gitignored data/normalized.
"""
import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.book_inventory_repository import BookInventoryRepository
from repositories.fact_store import create_fact_store
from repositories.fact_repository import FactRepository
from repositories.fact_query_repository import FactQueryRepository
from services.fact_query_service import FactQueryService
from services.book_inventory_service import BookInventoryService
from services.slim_review_service import select_dataset, synthetic_dataset, REAL_SLIM, SYNTHETIC_SLIM


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(product, revision, inventory, *, synthetic_target=None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    output = ROOT / "data/normalized/review_slim" / stamp
    backup = output / "backup"
    backup.mkdir(parents=True, exist_ok=False)
    # Backup BEFORE data preparation. Include both original BOM/inventory files
    # and previous processed/audit files, without overwriting any earlier version.
    facts = FactQueryService(FactQueryRepository(FactRepository(create_fact_store())))
    bom = facts.query_bom(product, revision)
    if bom["status"] != "ok":
        raise ValueError("Published BOM not found")
    source_names = set()
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get("source_file"), str):
                source_names.add(value["source_file"])
            for v in value.values():
                visit(v)
        elif isinstance(value, list):
            for v in value:
                visit(v)
    visit(bom["provenance"])
    source_paths = {Path(inventory).resolve()}
    source_paths.update(p.resolve() for p in (ROOT / "data/raw").rglob("*") if p.is_file() and p.name in source_names)
    if len(source_paths) < 2:
        raise ValueError("Cannot locate original BOM file for source backup")
    audits = ROOT / "data/facts/confirmations"
    source_paths.update(p for p in audits.glob("*.json"))
    previous_profile = audits / "review_slim.json"
    if previous_profile.exists():
        previous = json.loads(previous_profile.read_text(encoding="utf-8"))
        for value in previous.values():
            source_paths.update(p for p in (ROOT / value).parent.glob("*.json"))
    source_paths.update(p for p in (ROOT / "data/normalized").glob("*kq*json"))
    backup_manifest = []
    for i, path in enumerate(sorted(source_paths)):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        dest = backup / f"{i:02d}-{path.name}"
        shutil.copy2(path, dest)
        if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
            raise ValueError("Backup hash mismatch")
        backup_manifest.append(dict(original=str(path.relative_to(ROOT)), backup=str(dest.relative_to(ROOT)), sha256=digest))
    dump(output / "backup_manifest.json", backup_manifest)
    service = BookInventoryService(facts, BookInventoryRepository(inventory))
    real = select_dataset(service, product, revision)
    real.update(dataset_version=stamp, display_product_code=f"{product}-REVIEW-SLIM")
    synthetic = synthetic_dataset(real, synthetic_target)
    synthetic["display_product_code"] = f"{product}-REVIEW-SLIM-SYNTHETIC"
    dump(output / "verified.json", real)
    dump(output / "synthetic.json", synthetic)
    dump(output / "excluded.json", real["excluded"])
    dump(output / "synthetic_supplements.json", synthetic["supplements"])
    dump(output / "material_aliases.json", real["material_aliases"])
    dump(output / "selection_audit.json", real["selection_audit"])
    checked = {}
    from services.slim_review_service import SlimReviewService
    for label, dataset in (("verified", real), ("synthetic", synthetic)):
        calculation = SlimReviewService(facts, dataset).analyze(product, quantity=None)
        if calculation["status"] != "ok":
            raise ValueError("New dataset cannot be calculated")
        maximum = calculation["data"]["theoretical_max_quantity"]
        assert maximum >= 1
        for quantity in (1, maximum, maximum + 1):
            result = SlimReviewService(facts, dataset).analyze(product, quantity=quantity)
            assert result["data"]["inventory_sufficient_for_requested"] is (quantity <= maximum)
        checked[label] = dict(maximum=maximum, limiting_materials=calculation["data"]["limiting_materials"])
    dump(output / "calculation_report.json", checked)
    # Audit all source files remain unchanged.
    for r in backup_manifest:
        if hashlib.sha256((ROOT / r["original"]).read_bytes()).hexdigest() != r["sha256"]:
            raise ValueError("Original changed during preparation")
    profile = {REAL_SLIM:str((output / "verified.json").relative_to(ROOT)).replace("\\", "/"),
        SYNTHETIC_SLIM:str((output / "synthetic.json").relative_to(ROOT)).replace("\\", "/")}
    dump(audits / "review_slim.json", profile)
    return dict(dataset_root=str(output.relative_to(ROOT)), retained=real["retained_material_count"],
        excluded=len(real["excluded"]), backup_count=len(backup_manifest), zero_stock_retained=real["zero_stock_retained"],
        real_maximum=checked["verified"]["maximum"], synthetic_maximum=checked["synthetic"]["maximum"],
        minimum_coverage_ratio=real["minimum_coverage_ratio"],
        synthetic_supplement_count=len(synthetic["supplements"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--synthetic-target", type=int, default=None,
        help="Explicit synthetic driver; default is twice the newly verified subset capacity, never an old cached limit")
    args = parser.parse_args()
    print(json.dumps(prepare(args.product,args.revision,args.inventory,synthetic_target=args.synthetic_target), ensure_ascii=False))
