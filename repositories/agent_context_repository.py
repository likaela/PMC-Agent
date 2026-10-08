"""Read-only published metadata for Agent context, without migrations or fact writes."""

from __future__ import annotations

from repositories.fact_query_repository import FactQueryRepository, _cursor_dicts


class AgentContextRepository:
    def __init__(self, facts: FactQueryRepository):
        self.facts = facts
        self.store = facts.store

    def resolve_product(self, code: str) -> dict | None:
        return self.facts.resolve_item(code)

    def bom_versions(self, canonical_code: str) -> list[dict]:
        return self.facts.list_published_bom_versions(canonical_code)

    def structure_evidence(self, code: str, revision: str | None) -> dict | None:
        """Describe a unique published structure, never select a production-valid BOM."""
        product = self.resolve_product(code)
        if product is None or product.get("ambiguous"):
            return None
        versions = self.bom_versions(str(product["material_code"]))
        if revision is not None:
            versions = [row for row in versions if row["version"] == revision]
        if len(versions) != 1:
            return None
        from services.fact_query_service import FactQueryService
        result = FactQueryService(self.facts).query_bom(str(product["material_code"]), str(versions[0]["version"]))
        return result if result["status"] == "ok" else None

    def latest_inventory_time(self) -> dict | None:
        """A published observation anchor, not a wall-clock/default business date."""
        # SQLite TEXT may carry different explicit offsets; compare instants, not strings.
        ordering = "julianday(s.snapshot_at)" if self.store.dialect == "sqlite" else "s.snapshot_at"
        with self.store.transaction() as connection:
            rows = _cursor_dicts(self.store.execute(connection,
                "SELECT s.snapshot_at, s.import_batch_id, s.source_sheet AS sheet_name, "
                "sf.original_filename AS source_file, sf.content_sha256 "
                "FROM inventory_snapshots s JOIN import_batches b ON b.id = s.import_batch_id "
                "JOIN source_files sf ON sf.id = s.source_file_id "
                "WHERE b.status = 'published' AND s.published_at IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM inventory_facts f WHERE f.inventory_snapshot_id = s.id) "
                f"ORDER BY {ordering} DESC, s.id LIMIT 1"))
        return rows[0] if rows else None


__all__ = ["AgentContextRepository"]
