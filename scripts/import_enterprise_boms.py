"""Audit all enterprise workbooks; explicitly stage/publish structural BOM facts.

Default command only reads raw workbooks and writes a private audit report.
Database migration is deliberately NOT implicit. Use existing FactRepository.migrate
only after tests and a verified SQLite backup. No inventory facts are fabricated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fact_layer.models import ImportBatchStatus
from repositories.bom_import_repository import BomWorkbookRepository, load_bom_import_mapping
from repositories.fact_query_repository import FactQueryRepository
from repositories.fact_repository import FactRepository
from repositories.fact_store import create_fact_store
from repositories.source_file_storage import hash_source_file
from services.bom_import_service import BomImportService
from services.fact_query_service import FactQueryService
from tools.published_product_tools import build_published_product_search

MAPPING = ROOT / "import_mappings/enterprise_structure_v1.json"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def audit_directory(raw_dir: Path, mapping_path: Path = MAPPING) -> dict:
    """No store/connection creation: metadata, numbers and conflicts only."""
    mapping = load_bom_import_mapping(mapping_path)
    reader, validator = BomWorkbookRepository(), BomImportService(None)
    files, candidates = [], []
    for source in sorted(raw_dir.rglob("*")):
        if not source.is_file() or source.suffix.lower() not in {".xls", ".xlsx"} or source.name.startswith("~$"):
            continue
        digest, size = hash_source_file(source)
        entry = dict(file=str(source.relative_to(raw_dir)), sha256=digest, byte_size=size,
                     classification="C", reason="未识别可靠 BOM 表头与父项/版本元数据", boms=[], excluded_sheets=[])
        files.append(entry)
        try:
            mapped = reader.map_workbook(source, mapping)
        except Exception as error:
            entry["reason"] = "工作簿读取或元数据冲突，不能自动发布"
            entry["error_type"] = type(error).__name__
            continue
        entry["detected_sheets"] = list(mapped.detected_sheets)
        sheet_rows = defaultdict(list)
        for row in mapped.rows:
            sheet_rows[row.sheet_name].append(row)
        groups = defaultdict(list)
        for sheet in mapped.detected_sheets:
            rows = sheet_rows[sheet]
            identities = {(row.parent_material_code, row.version) for row in rows}
            if not rows or len(identities) != 1 or not all(next(iter(identities))):
                entry["excluded_sheets"].append(dict(sheet=sheet, reason="无有效明细或缺少唯一父项/版本；不将辅助表视为 BOM"))
                continue
            groups[next(iter(identities))].extend(rows)
        for (product, revision), rows in groups.items():
            seen, errors, lines = set(), [], []
            for row in rows:
                staged, found = validator._validate_row("audit", "source", row, mapping, Decimal(mapping.total_price_tolerance), seen)
                errors.extend(dict(sheet=e.sheet_name, row=e.source_row_number, code=e.error_code, reason=e.message) for e in found)
                lines.append(dict(parent=product, child=staged.material_code, name=staged.material_name,
                    qty_per=str(staged.quantity) if staged.quantity is not None else None,
                    unit=staged.unit, source_unit_price=str(staged.tax_included_unit_price) if staged.tax_included_unit_price is not None else None,
                    source_total_price=str(staged.source_total_price) if staged.source_total_price is not None else None,
                    currency=staged.currency, effective_from=str(staged.effective_from) if staged.effective_from else None,
                    sheet=row.sheet_name, row=row.source_row_number, metadata_row=row.metadata_row_number))
            bom = dict(file=entry["file"], sha256=digest, byte_size=size, product=product,
                product_name=None, revision=revision, source_level="direct_relationships_only",
                sheets=sorted({row.sheet_name for row in rows}), line_count=len(lines),
                classification="B" if errors else "A", errors=errors, lines=lines,
                completeness=dict(unit=all(line["unit"] is not None for line in lines),
                    source_price=all(line["source_unit_price"] is not None for line in lines),
                    effective_from=all(line["effective_from"] is not None for line in lines)),
                capabilities=dict(bom_structure_query=not errors, deterministic_production_analysis=False, price_analysis=False))
            entry["boms"].append(bom)
            candidates.append(bom)
        entry["classification"] = "A" if entry["boms"] and all(bom["classification"] == "A" for bom in entry["boms"]) else "B" if entry["boms"] else "C"
        if entry["boms"]:
            entry["reason"] = "元数据及数量可核验；只发布结构，未知字段不补值"
    counts = Counter((bom["product"], bom["revision"]) for bom in candidates)
    for bom in candidates:
        if counts[(bom["product"], bom["revision"])] > 1:
            bom["classification"] = "B"
            bom["errors"].append(dict(code="DUPLICATE_PRODUCT_REVISION", reason="多个源文件有相同产品/版本，必须人工确认，不覆盖"))
    for entry in files:
        if entry["boms"] and any(bom["classification"] != "A" for bom in entry["boms"]):
            entry["classification"] = "B"
    return dict(audited_at=datetime.now(UTC).isoformat(), files=files, boms=candidates,
                counts=dict(workbooks=len(files), bom_files=sum(bool(entry["boms"]) for entry in files),
                    products=len({bom["product"] for bom in candidates}), safe_boms=sum(bom["classification"] == "A" for bom in candidates)))


def _verified_source(raw_dir: Path, bom: dict) -> Path:
    root = raw_dir.resolve()
    path = (root / bom["file"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("源文件必须位于受控 raw 目录内")
    if hash_source_file(path) != (bom["sha256"], bom["byte_size"]):
        raise ValueError("源文件与审计哈希不一致，须重新预检")
    return path


def stage_audited(audit: dict, raw_dir: Path, repository: FactRepository, output_dir: Path, *,
                  confirmed_by: str, reason: str, confirmations: dict | None = None) -> list[dict]:
    """All safe BOMs staged and validated BEFORE any publication."""
    if not confirmed_by.strip() or not reason.strip():
        raise ValueError("必须明确结构发布授权人及依据")
    service = BomImportService(repository)
    manifest = []
    base = json.loads(MAPPING.read_text(encoding="utf-8"))
    for bom in audit["boms"]:
        if bom["classification"] != "A":
            continue
        path = _verified_source(raw_dir, bom)
        profile = {**base, "included_sheets": bom["sheets"]}
        mapping_path = output_dir / "mappings" / f"{bom['sha256']}-{hashlib.sha256(json.dumps(bom['sheets']).encode()).hexdigest()[:12]}.json"
        write_json(mapping_path, profile)
        staged = service.stage_bom(path, mapping_path)
        if staged.error_count:
            raise ValueError(f"暂存校验失败，批次保留错误供审计：{staged.import_batch_id}")
        selected = (confirmations or {}).get(bom["product"], {})
        unknown = set(selected) - {"effective_from"}
        if unknown:
            raise ValueError("该结构导入入口仅接受显式确认生效日期；不推断单位、币种、库存")
        if selected:
            service.confirm_pending_fields(staged.import_batch_id, selected, confirmed_by=confirmed_by, reason=reason)
        repository.confirm_structure_publication(staged.import_batch_id, confirmed_by=confirmed_by, reason=reason)
        batch = repository.get_import_batch(staged.import_batch_id)
        rows = repository.get_staged_rows(staged.import_batch_id)
        header = repository.get_staged_header(staged.import_batch_id)
        source = repository.get_source_file(rows[0].source_file_id)
        expected = [(line["sheet"], line["row"], line["child"], Decimal(line["qty_per"])) for line in bom["lines"]]
        actual = [(row.sheet_name, row.source_row_number, row.material_code, row.quantity) for row in rows]
        if (batch.status != ImportBatchStatus.READY_TO_PUBLISH or batch.error_count or batch.pending_confirmation_fields
            or len(rows) != bom["line_count"] or actual != expected
            or (header.parent_material_code, header.version) != (bom["product"], bom["revision"])
            or source.content_sha256 != bom["sha256"]):
            raise ValueError("暂存数量/身份/来源与审计不一致，停止发布")
        manifest.append(dict(import_batch_id=batch.id, product=bom["product"], revision=bom["revision"],
            line_count=len(rows), file=bom["file"], sha256=bom["sha256"], byte_size=bom["byte_size"],
            lines=bom["lines"], status=batch.status.value))
    return manifest


def publish_staged(manifest: list[dict], raw_dir: Path, repository: FactRepository) -> list[dict]:
    """Recheck ALL sources and rows before publishing; repository locks each batch."""
    for entry in manifest:
        _verified_source(raw_dir, entry)
        rows = repository.get_staged_rows(entry["import_batch_id"])
        header = repository.get_staged_header(entry["import_batch_id"])
        batch = repository.get_import_batch(entry["import_batch_id"])
        if not header or not batch or header.publication_scope != "structure" or batch.status != ImportBatchStatus.READY_TO_PUBLISH:
            raise ValueError("批次尚未准备好；不跳过失败或已发布批次")
        source = repository.get_source_file(header.source_file_id)
        if not source or source.content_sha256 != entry["sha256"] or batch.error_count or batch.pending_confirmation_fields:
            raise ValueError("暂存来源或校验状态不一致")
        if [(r.sheet_name, r.source_row_number, r.material_code, r.quantity) for r in rows] != [
                (line["sheet"], line["row"], line["child"], Decimal(line["qty_per"])) for line in entry["lines"]]:
            raise ValueError("暂存明细已变化，停止发布")
        if (header.parent_material_code, header.version) != (entry["product"], entry["revision"]):
            raise ValueError("暂存父项/版本不一致")
        if repository.get_published_bom(entry["product"], entry["revision"]) is not None:
            raise ValueError("同父项同版本已发布：reject，不覆盖")
    return [repository.publish_batch(entry["import_batch_id"]) for entry in manifest]


def backup_sqlite(database: Path, destination: Path) -> dict:
    """SQLite online backup includes WAL, opens source read-only, never overwrites."""
    if not database.is_file() or destination.exists() or database.resolve() == destination.resolve():
        raise ValueError("备份源不存在或备份目标已存在")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(destination) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("备份完整性校验失败")
    return dict(path=str(destination), sha256=hash_source_file(destination)[0])


def published_catalog(repository: FactRepository) -> list[dict]:
    """Only published facts feed the judge catalog; never copy raw rows."""
    tool = build_published_product_search(repository.store)
    result = tool.invoke({"limit": 100})
    if result["status"] == "data_unavailable":
        return []
    if result["status"] != "ok" or result["data"]["truncated"]:
        raise ValueError("目录查询失败或被截断，不能生成不完整试用目录")
    facts = FactQueryService(FactQueryRepository(repository))
    catalog = []
    for product in result["data"]["products"]:
        for version in product["revisions"]:
            bom = facts.query_bom(product["product_code"], version["revision"])
            if bom["status"] != "ok":
                raise ValueError("已发布产品无法查询对应 BOM")
            catalog.append(dict(product=product["product_code"], name=product["product_name"], revision=version["revision"],
                line_count=bom["data"]["line_count"], effective_from=bom["data"]["effective_from"],
                completeness=bom["completeness"], provenance=bom["provenance"], warnings=bom["warnings"],
                capabilities={"product_discovery": True, "bom_structure_query": True,
                    "deterministic_production_analysis": False, "price_analysis": False}))
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--report", type=Path, default=ROOT / "data/normalized/enterprise_bom_import_report.json")
    parser.add_argument("--stage", action="store_true")
    parser.add_argument("--publish-manifest", type=Path, help="发布已核验暂存清单；不重复 staging")
    parser.add_argument("--confirmed-by")
    parser.add_argument("--reason")
    parser.add_argument("--confirmations", type=Path, help='产品编码到 {"effective_from":"YYYY-MM-DD"}，不填未知日期')
    args = parser.parse_args()
    if args.stage and args.publish_manifest:
        parser.error("staging 与 publish 必须分两步执行")
    if args.stage:
        if not args.confirmed_by or not args.reason:
            parser.error("--stage 须显式提供授权人与依据")
        audit = audit_directory(args.raw_dir)
        repository = FactRepository(create_fact_store())
        confirmations = json.loads(args.confirmations.read_text(encoding="utf-8")) if args.confirmations else {}
        audit["staged"] = stage_audited(audit, args.raw_dir, repository, args.report.parent,
                                      confirmed_by=args.confirmed_by, reason=args.reason, confirmations=confirmations)
        write_json(args.report, audit)
        write_json(args.report.parent / "enterprise_bom_staging_manifest.json", audit["staged"])
    elif args.publish_manifest:
        repository = FactRepository(create_fact_store())
        manifest = json.loads(args.publish_manifest.read_text(encoding="utf-8"))
        published = publish_staged(manifest, args.raw_dir, repository)
        write_json(args.report.parent / "enterprise_bom_publication_report.json", {"published": published, "catalog": published_catalog(repository)})
        print(json.dumps(published, ensure_ascii=False))
    else:
        audit = audit_directory(args.raw_dir)
        write_json(args.report, audit)
        print(json.dumps(audit["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
