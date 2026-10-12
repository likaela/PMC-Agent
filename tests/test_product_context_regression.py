"""Real scoped Agent/Tool calls over synthetic fixtures, never private model egress."""
import copy
from unittest.mock import patch
import pytest
from agents.product_resolver import resolve_product, product_overview_requested
from tests.test_reviewer_default_scope import filtered
from tests.test_slim_review_scenario import selected
from tests.test_enterprise_book_analysis import book
from tests.test_published_bom_business_confirmation import fixture
from tests.test_authorized_review import new, ask

CATALOG = [dict(product_code="KQ-EXAMPLE", synthetic=False), dict(product_code="DEMO-PMC-01", synthetic=True)]

@pytest.mark.parametrize("message", ["演示产品", "Demo产品", "DEMO", "demo", "演示用产品", "那个演示产品", "查一下Demo", "看看演示产品", "切换到演示产品", "查询演示产品的BOM"])
def test_alias_supersedes_history(message):
    result = resolve_product(message, CATALOG, current_product="KQ-EXAMPLE")
    assert result["product_code"] == "DEMO-PMC-01" and result["explicit"]
    assert "DEMO-PMC-01" in result["message"]
    assert product_overview_requested(result["message"], result["product_code"]) == ("BOM" not in message)

def test_ambiguity_exact_short_code_permission_and_ordinal():
    assert resolve_product("换成EXAMPLE", CATALOG)["product_code"] == "KQ-EXAMPLE"
    assert resolve_product("查询demo", CATALOG + [dict(product_code="DEMO-B", synthetic=True)])["status"] == "needs_input"
    assert resolve_product("查询demo", CATALOG[:1], current_product="KQ-EXAMPLE")["status"] == "item_not_found"
    assert resolve_product("查询KQ-NOT-EXIST", CATALOG, current_product="KQ-EXAMPLE")["status"] == "item_not_found"
    assert resolve_product("切换到第一个产品", CATALOG)["status"] == "needs_input"
    assert resolve_product("切换到第一个产品", CATALOG, catalog_order=["KQ-EXAMPLE"])["product_code"] == "KQ-EXAMPLE"
    assert resolve_product("有哪些产品", CATALOG, current_product="KQ-EXAMPLE")["product_code"] is None
    assert resolve_product("查询KQ-EXAMPLE已发布BOM", CATALOG)["product_code"] == "KQ-EXAMPLE"
    assert resolve_product("demo，改查KQ-EXAMPLE", CATALOG)["product_code"] == "KQ-EXAMPLE"

def test_scoped_switch_history_no_old_quantity_and_catalog_no_switch(filtered):
    binding, client = filtered
    original = new(client)
    first = ask(client, original, "生产1片").json()
    resolved = client.post("/api/v1/review/resolve", json={"message":"查询演示产品", "session_id":original}).json()
    assert resolved["product_code"] == "DEMO-PMC-01"
    assert ask(client, original, "查询演示产品").status_code == 409
    demo = new(client, resolved["product_code"])
    overview = ask(client, demo, "查询演示产品").json()
    assert overview["structured_data"]["query_type"] == "product_overview"
    assert "theoretical_max_quantity" not in overview["structured_data"]["data"]
    assert binding.services["DEMO-PMC-01"].repository.get_session(demo)["context"]["production"]["quantity"] is None
    production = ask(client, demo, "生产50台").json()
    assert production["structured_data"]["data"]["requested_quantity"] == 50
    assert production["structured_data"]["data"]["inventory_sufficient_for_requested"]
    assert "最大" not in production["answer"]
    directory = ask(client, demo, "有哪些产品").json()
    assert directory["structured_data"]["query_type"] == "product_search"
    assert directory["review_product"] == "DEMO-PMC-01"
    assert client.get(f"/api/v1/agent/sessions/{original}").json()["turns"][0]["response"]["structured_data"]["data"] == first["structured_data"]["data"]
    client.headers["X-PMC-User"] = "b"
    assert client.post("/api/v1/review/resolve", json={"message":"查询演示产品", "session_id":original}).status_code == 404

@pytest.mark.parametrize("message,kind", [("查询BOM", "bom"), ("查看库存", "inventory"), ("生产1片", "production_capacity"), ("最多能生产多少", "production_capacity")])
def test_intent_presentation_and_evidence_preservation(filtered, message, kind):
    binding, client = filtered
    sid = new(client)
    response = ask(client, sid, message).json()
    assert response["structured_data"]["query_type"] == kind
    assert response["structured_data"]["presentation"]["show_maximum"] == ("最多" in message)
    assert ("最大满足数量" in response["answer"]) == ("最多" in message)
    history = binding.slim.repository.history(sid)
    assert history["turns"][0]["fact_references"][0]["result"]["data"]["theoretical_max_quantity"] >= 1

def test_zero_no_tool_and_explanation_reuses_last_quantity(filtered):
    binding, client = filtered
    sid = new(client)
    r = ask(client, sid, "生产2片").json()
    context = copy.deepcopy(binding.slim.repository.get_session(sid)["context"])
    with patch.object(binding.slim.book_service.observations,"load",side_effect=AssertionError("No repeated Tool")):
        assert ask(client,sid,"生产0片").json()["status"] == "invalid_query"
        why=ask(client,sid,"为什么不行").json()
    assert why["structured_data"]["reused_from_turn_id"] == r["turn_id"]
    assert why["structured_data"]["data"]["requested_quantity"] == 2
    assert binding.slim.repository.get_session(sid)["context"] == context
    assert "最大" not in why["answer"]


def test_demo_pronoun_bom_and_explanation_use_bound_product_and_evidence(filtered):
    binding, client = filtered
    sid = new(client, "DEMO-PMC-01")
    result = ask(client, sid, "看看它的BOM").json()
    assert result["intent"] == "bom"
    assert result["structured_data"]["data"]["line_count"] == 3
    production = ask(client, sid, "生产100台").json()
    assert production["structured_data"]["data"]["requested_quantity"] == 100
    why = ask(client, sid, "为什么不行").json()
    assert why["structured_data"]["reused_from_turn_id"] == production["turn_id"]
    assert why["structured_data"]["completed_steps"] == []
    assert why["structured_data"]["reused_result"]["data"]["requested_quantity"] == 100
    before = copy.deepcopy(binding.services["DEMO-PMC-01"].repository.get_session(sid)["context"])
    with patch.object(binding.services["DEMO-PMC-01"].orchestrator.registry, "resolve", side_effect=AssertionError("Zero must not resolve a Tool")):
        zero = ask(client, sid, "生产0台").json()
    assert zero["status"] == "needs_input"
    assert zero["structured_data"]["completed_steps"] == []
    assert binding.services["DEMO-PMC-01"].repository.get_session(sid)["context"] == before


def test_child_query_does_not_replace_bound_product():
    from api.routes.agent import _product_context
    context = dict(active_domain="fact", fact=dict(material_code="MAT-001"),
        production=dict(material_code="KQ-EXAMPLE", revision="V01"),
        product_context=dict(product_code="KQ-EXAMPLE", scenario_id=None, revision="V01"))
    assert _product_context(context)["product_code"] == "KQ-EXAMPLE"


def test_ordinal_query_transport_keeps_original_and_checks_owner(filtered):
    _, client = filtered
    sid = new(client, "DEMO-PMC-01")
    question = "切换到第一个产品"
    result = ask(client, sid, question, catalog_order=["DEMO-PMC-01"]).json()
    assert result["structured_data"]["query_type"] == "product_overview"
    saved = client.get(f"/api/v1/agent/sessions/{sid}").json()
    assert saved["turns"][-1]["user_query"] == question
    # Catalog ordering never grants access or bypasses the immutable session binding.
    assert ask(client, sid, question, catalog_order=["ENTERPRISE-A"]).status_code == 409
    assert ask(client, sid, question, catalog_order=["KQ-UNAUTHORIZED"]).status_code == 422


def test_explicit_product_published_bom_is_not_a_catalog(filtered):
    _, client = filtered
    sid = new(client)
    result = ask(client, sid, "查询ENTERPRISE-A已发布BOM").json()
    assert result["structured_data"]["query_type"] == "bom"
    assert result["structured_data"]["data"]["product"] == "ENTERPRISE-A"
    assert "products" not in result["structured_data"]["data"]


def test_relative_quantity_requires_same_product_and_known_target(filtered):
    binding, client = filtered
    sid = new(client, "DEMO-PMC-01")
    with patch.object(binding.services["DEMO-PMC-01"].orchestrator.registry, "resolve", side_effect=AssertionError("No relative baseline")):
        ambiguous = ask(client, sid, "再多生产1台呢").json()
    assert ambiguous["status"] == "needs_input"
    assert ambiguous["structured_data"]["completed_steps"] == []
    ask(client, sid, "生产50台")
    actual = ask(client, sid, "再多生产1台呢").json()
    assert actual["structured_data"]["data"]["requested_quantity"] == 51
    saved = client.get(f"/api/v1/agent/sessions/{sid}").json()
    assert saved["turns"][-1]["user_query"] == "再多生产1台呢"
