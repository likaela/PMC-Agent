"""Synthetic artifact tests; never open enterprise files or databases."""
import json
import pytest
from scripts.audit_trial_bundle import audit

@pytest.fixture
def artifact(tmp_path):
    (tmp_path / "index.html").write_text('<script type="module" src="/assets/index.js"></script>', encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/index.js").write_text('const product="DEMO-PMC-01";', encoding="utf-8")
    (tmp_path / "module-closure.json").write_text(json.dumps(["trial/useTrialAgent.ts", "trial/scenarioPolicy.ts"]), encoding="utf-8")
    return tmp_path

def test_pure_synthetic_artifact_passes(artifact):
    assert audit(artifact)["source_maps"] == 0

@pytest.mark.parametrize("content", ["KQ-EXAMPLE", "review_real_bom_simulation", "data/raw/example.xls", "E:/private/source.xls", "sk-" + "x" * 24])
def test_rejects_private_identifiers_in_any_asset(artifact, content):
    (artifact / "unexpected.txt").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe trial resource"):
        audit(artifact)

def test_rejects_source_maps(artifact):
    (artifact / "assets/index.js.map").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError): audit(artifact)

def test_rejects_enterprise_module_even_without_identifiers(artifact):
    (artifact / "module-closure.json").write_text(json.dumps(["trial/useTrialAgent.ts", "trial/scenarioPolicy.ts", "src/composables/useAgent.ts"]), encoding="utf-8")
    with pytest.raises(ValueError, match="Private application entry"):
        audit(artifact)
