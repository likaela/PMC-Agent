"""Default read-only precheck; --apply requires evidence verification and backup.

Use only explicitly human-confirmed values. This does not import or publish stock.
Acceptance context is opt-in for newly created internal sessions, never global.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # Load the same .env as the backend, never print secrets.
from repositories.agent_conversation_repository import AgentConversationRepository
from repositories.fact_store import SQLiteFactStore, create_fact_store
from repositories.published_bom_confirmation_repository import PublishedBomConfirmationRepository
from scripts.import_enterprise_boms import backup_sqlite
from services.published_bom_confirmation_service import ConfirmationRequest, PublishedBomConfirmationService


def sha256(path):
    with Path(path).open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256")
    return digest.hexdigest()


def execute(request, store, *, apply=False, evidence_file=None, backup_dir=None, create_acceptance_session=False):
    repository = PublishedBomConfirmationRepository(store)
    service = PublishedBomConfirmationService(repository)
    manifest = service.precheck(request)
    result = {"mode": "precheck", "manifest": manifest, "request": request.model_dump(),
              "inventory_published": False,
              "parent_units_confirmed": all(p.parent_unit is not None for p in request.products),
              "inventory_units_confirmed": False}
    if not apply:
        return result
    if not isinstance(store, SQLiteFactStore):
        raise ValueError("This release command requires a verified SQLite online backup; use an approved PostgreSQL backup workflow otherwise")
    if evidence_file is None or sha256(evidence_file) != request.evidence_sha256:
        raise ValueError("Human confirmation evidence SHA-256 mismatch")
    database = Path(store.database_path).resolve()
    result["database_before_sha256"] = sha256(database)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = Path(backup_dir or database.parent / "backups") / f"before-business-confirmation-{stamp}.db"
    result["backup"] = backup_sqlite(database, destination)
    backed_up = PublishedBomConfirmationService(
        PublishedBomConfirmationRepository(SQLiteFactStore(destination))).precheck(request)
    if backed_up != manifest:
        raise ValueError("Backup BOM facts differ from the validated manifest; no update executed")
    result["backup_bom_manifest_verified"] = True
    # Retain immutable private human evidence, independent of clipboard/temp lifetime.
    evidence_destination = database.parent / "confirmations" / f"{request.evidence_sha256}.txt"
    evidence_destination.parent.mkdir(parents=True, exist_ok=True)
    if evidence_destination.exists():
        if sha256(evidence_destination) != request.evidence_sha256:
            raise ValueError("Private confirmation evidence has been modified")
    else:
        content = Path(evidence_file).read_bytes()
        if hashlib.sha256(content).hexdigest() != request.evidence_sha256:
            raise ValueError("Confirmation evidence changed while copying")
        with evidence_destination.open("xb") as handle:
            handle.write(content)
    result["private_evidence_copy"] = {"path": str(evidence_destination), "sha256": sha256(evidence_destination)}
    result["migrations"] = store.migrate()
    result["events"] = service.apply(request, manifest)
    result["after_manifest"] = service.precheck(request)
    result["database_after_facts_sha256"] = sha256(database)
    result["mode"] = "applied"
    if create_acceptance_session:
        context = repository.scoped_context([event["confirmation_id"] for event in result["events"]])
        result["acceptance_session"] = AgentConversationRepository(store).create_session(initial_context=context)
    result["database_after_session_sha256"] = sha256(database)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirmation-file", required=True, type=Path)
    parser.add_argument("--evidence-file", type=Path)
    parser.add_argument("--database-url")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--create-acceptance-session", action="store_true")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    request = ConfirmationRequest.model_validate_json(args.confirmation_file.read_text(encoding="utf-8"))
    result = execute(request, create_fact_store(args.database_url), apply=args.apply,
                     evidence_file=args.evidence_file, create_acceptance_session=args.create_acceptance_session)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"mode": result["mode"], "products": len(result["manifest"]),
                      "lines": sum(len(row["state"]["lines"]) for row in result["manifest"]),
                      "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
