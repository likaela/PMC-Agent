"""Freeze catalog/date-scope regressions on synthetic facts, without model egress."""
import copy
from unittest.mock import Mock, patch

import pytest

from agents.planner import AgentPlanner
from repositories.agent_context_repository import AgentContextRepository
from repositories.agent_conversation_repository import AgentConversationRepository
from repositories.fact_query_repository import FactQueryRepository
from services.persistent_agent_service import PersistentAgentService
from services.published_bom_confirmation_service import ConfirmationRequest
from tests.test_published_bom_business_confirmation import fixture, apply
from tests.test_parent_unit_confirmation_acceptance import agent, confirm_parents, parent_request


CATALOG = ['查询已发布的BOM', '查询已发布BOM的产品', '已发布BOM的产品有哪些', '有哪些已发布产品']


@pytest.mark.parametrize('message', CATALOG)
@pytest.mark.parametrize('existing_task', [False, True])
def test_catalog_synonyms_ignore_task_without_inventing_category(fixture, message, existing_task):
    service, session = agent(fixture)
    if existing_task:
        service.query(session, '2026年9月16日生产100片ENTERPRISE-A可以吗')
    before = copy.deepcopy(service.repository.get_session(session)['context'])
    response = service.query(session, message)
    assert response['intent'] == 'fact_query' and response['status'] == 'ok'
    assert response['structured_data']['query']['search_term'] is None
    assert {p['product_code'] for p in response['structured_data']['data']['products']} == {'ENTERPRISE-A', 'ENTERPRISE-B'}
    assert service.repository.get_session(session)['context'] == before
    refs = service.repository.history(session)['turns'][-1]['fact_references']
    assert [r['tool_name'] for r in refs] == ['published_product_search']


def test_catalog_with_explicit_product_is_still_exact_bom_query(fixture):
    service, session = agent(fixture)
    response = service.query(session, '查询已发布的BOM ENTERPRISE-A')
    assert response['intent'] == 'bom'
    assert response['structured_data']['data']['line_count'] == 66


@pytest.mark.parametrize('existing_task', [False, True])
def test_quantity_is_first_question_and_new_order_does_not_reuse_old_quantity(fixture, existing_task):
    service, session = agent(fixture)
    if existing_task:
        service.query(session, '2026年9月16日生产100片ENTERPRISE-A可以吗')
    with patch.object(service.orchestrator.registry, 'resolve', side_effect=AssertionError('No calculation')):
        response = service.query(session, '我要生产ENTERPRISE-A')
    assert response['intent'] == 'production_capacity' and response['status'] == 'needs_input'
    assert response['structured_data']['missing_fields'] == ['生产数量']
    assert response['answer'].index('请先补充生产数量') < response['answer'].index('库存')
    assert '2026-09-15' in response['answer'] and '2026-09-11' in response['answer']
    assert response['structured_data']['query']['quantity'] is None
    assert service.repository.get_session(session)['context']['production']['material_code'] == 'ENTERPRISE-A'
    if not existing_task:
        assert response['structured_data']['query']['effective_date'] is None


def test_llm_cannot_revive_previous_order_quantity():
    context = {'active_domain': 'production', 'production': dict(query_type='production_capacity', material_code='ENTERPRISE-A', quantity=100)}
    model = Mock()
    model.with_structured_output.return_value.invoke.return_value = dict(intent='production_capacity',
        entities={'material_code': 'ENTERPRISE-A', 'quantity': 100}, required_tools=['production_analysis'], missing_parameters=[])
    plan, source = AgentPlanner(llm_status=lambda: {'status': 'ok'}, llm_factory=lambda: model).plan('我要生产ENTERPRISE-A', context)
    assert plan.entities.quantity is None and source == 'rule_fallback'


@pytest.mark.parametrize('code,count', [('ENTERPRISE-A', 66), ('ENTERPRISE-B', 91)])
def test_explicit_date_does_not_reask_confirmed_fields_and_stock_date_is_not_snapshot(fixture, code, count):
    service, session = agent(fixture)
    response = service.query(session, f'2026年9月16日生产1片{code}可以吗')
    query = response['structured_data']['query']
    assert query['effective_date'] == '2026-09-16' and query['as_of'] is None
    assert response['status'] == 'data_unavailable'
    assert response['structured_data']['published_bom_summary']['line_count'] == count
    assert response['structured_data']['business_decision']['status'] == 'NOT_APPROVED'
    assert '2026-09-15' in response['answer'] and '2026-09-11' in response['answer'] and 'UTC+08:00' in response['answer']
    assert '尚未确认具体时刻' in response['answer']
    assert not any(text in response['answer'] for text in ['物料计量单位尚未确认', 'BOM的生效日期尚未确认', '请确认生产分析日期'])


def test_explicit_audited_scenario_binds_then_restores_without_global_default(fixture):
    service, session = agent(fixture)
    service.query(session, '查询ENTERPRISE-A的BOM')
    response = service.query(session, '按照之前确认的2026年9月16日业务情境分析生产100片')
    assert response['structured_data']['query']['effective_date'] == '2026-09-16'
    context = service.repository.get_session(session)['context']
    assert context['confirmed_analysis_scope']['ENTERPRISE-A']
    refs = service.repository.history(session)['turns'][-1]['fact_references']
    assert any(r['result']['provenance'].get('date_basis', {}).get('source') == 'audited_session_business_context' for r in refs)
    restarted = PersistentAgentService(AgentConversationRepository(fixture[0]))
    restarted.enable_orchestrator()
    follow = restarted.query(session, '按之前指定业务情境继续分析')
    assert follow['structured_data']['query']['effective_date'] == '2026-09-16'
    with patch.object(restarted.orchestrator.registry, 'resolve', side_effect=AssertionError('No recomputation')):
        why = restarted.query(session, '为什么还不能批准')
    assert why['structured_data']['reused_result'] and '生产100片' in why['answer']
    fresh = restarted.repository.create_session()['session_id']
    response = restarted.query(fresh, '生产100片ENTERPRISE-A可以吗')
    assert response['structured_data']['query']['effective_date'] is None
    assert '本次生产分析日期为 2026-09-16' not in response['answer']


def test_explicit_scenario_never_borrows_another_product(fixture):
    service, session = agent(fixture)
    response = service.query(session, '按之前指定业务情境分析生产100片UNKNOWN-PRODUCT')
    assert response['status'] == 'data_unavailable'
    assert response['structured_data']['query']['effective_date'] is None
    assert not service.repository.get_session(session)['context'].get('confirmed_analysis_scope')


def test_conflicting_audits_require_explicit_date_and_preserve_facts(fixture):
    service, session = agent(fixture)
    data = parent_request(fixture).model_dump()
    data['products'] = [data['products'][0]]
    data['products'][0]['analysis_date'] = '2026-09-17'
    request = ConfirmationRequest.model_validate(data)
    fixture[4].apply(request, fixture[4].precheck(request))
    service.query(session, '查询ENTERPRISE-A的BOM')
    response = service.query(session, '按之前指定业务情境分析生产100片')
    assert response['status'] == 'needs_input' and '多个已确认业务情境' in response['answer']
    assert not service.repository.get_session(session)['context'].get('confirmed_analysis_scope')
    response = service.query(session, '按之前确认的2026年9月16日业务情境分析生产100片')
    assert response['structured_data']['query']['effective_date'] == '2026-09-16'


def test_old_scope_requires_reconfirmation_not_database_republication(fixture):
    first = apply(fixture)
    repository = AgentConversationRepository(fixture[0])
    old = repository.create_session(initial_context=fixture[3].scoped_context([e['confirmation_id'] for e in first]))['session_id']
    confirm_parents(fixture)
    service = PersistentAgentService(repository)
    service.enable_orchestrator()
    response = service.query(old, '生产100片ENTERPRISE-A可以吗')
    assert '原会话绑定的业务确认已更新' in response['answer']
    before = repository.history(old)['turns'][0]
    response = service.query(old, '按之前指定业务情境继续分析')
    assert response['structured_data']['query']['effective_date'] == '2026-09-16'
    assert repository.history(old)['turns'][0] == before
    assert repository.get_session(old)['context']['confirmed_analysis_scope']['ENTERPRISE-A'] != first[0]['confirmation_id']
    with fixture[0].transaction() as connection:
        assert connection.execute('select count(*) from bom_lines').fetchone()[0] == 157
        assert connection.execute('select count(*) from inventory_snapshots').fetchone()[0] == 0


def test_repository_has_no_audit_date_default_and_explicit_request_is_exact(fixture):
    confirm_parents(fixture)
    repository = AgentContextRepository(FactQueryRepository(fixture[1]))
    assert 'analysis_date' not in repository.published_business_fields('ENTERPRISE-A', 'V01')
    assert repository.requested_analysis_context('ENTERPRISE-A', 'V02', None)['context'] is None
    assert repository.requested_analysis_context('ENTERPRISE-A', None, '2026-10-20')['context'] is None


def test_explicit_date_survives_quantity_followup_but_not_new_session(fixture):
    service, session = agent(fixture)
    service.query(session, '2026年9月16日生产100片ENTERPRISE-A可以吗')
    response = service.query(session, '减少到50片可以吗')
    assert response['structured_data']['query']['effective_date'] == '2026-09-16'
    assert response['structured_data']['query']['quantity'] == 50
    with patch.object(service.orchestrator.registry, 'resolve', side_effect=AssertionError('No calculation')):
        response = service.query(session, '我要生产ENTERPRISE-A')
    assert '本次生产分析日期为 2026-09-16' in response['answer']
    assert '请同时明确本次生产分析日期' not in response['answer']


def test_relative_new_plan_never_uses_previous_explicit_date(fixture):
    service, session = agent(fixture)
    service.query(session, '2026年9月16日生产100片ENTERPRISE-A可以吗')
    response = service.query(session, '下周生产是否有风险')
    assert response['status'] == 'needs_input'
    assert '请确认具体的业务日期' in response['answer']
    assert response['structured_data']['query']['effective_date'] is None
    assert '本次生产分析日期为 2026-09-16' not in response['answer']


def test_failed_product_reason_cannot_masquerade_as_previous_success(fixture):
    service, session = agent(fixture)
    service.query(session, '查询ENTERPRISE-A的BOM')
    before = copy.deepcopy(service.repository.get_session(session)['context']['fact'])
    with patch.object(service.orchestrator.registry, 'resolve', side_effect=RuntimeError('private failure')):
        failed = service.query(session, '查询ENTERPRISE-B的BOM')
    assert failed['status'] == 'query_failed'
    with patch.object(service.orchestrator.registry, 'resolve', side_effect=AssertionError('No old-object query')):
        why = service.query(session, '为什么')
    assert why['status'] == 'query_failed' and 'ENTERPRISE-B' in why['answer']
    assert 'ENTERPRISE-A' not in why['answer'] and not why['structured_data'].get('reused_result')
    assert service.repository.get_session(session)['context']['fact'] == before
    assert service.repository.history(session)['turns'][-1]['fact_references'] == []
    retry = service.query(session, '再查一次')
    assert retry['status'] == 'ok' and retry['structured_data']['data']['parent_item']['material_code'] == 'ENTERPRISE-B'
    assert not service.repository.get_session(session)['context'].get('last_query_failure')


def test_failed_request_does_not_prevent_explicit_old_product_explanation(fixture):
    service, session = agent(fixture)
    service.query(session, '查询ENTERPRISE-A的BOM')
    with patch.object(service.orchestrator.registry, 'resolve', side_effect=RuntimeError('private failure')):
        service.query(session, '查询ENTERPRISE-B的BOM')
    response = service.query(session, 'ENTERPRISE-A的来源是什么')
    assert response['structured_data']['reused_result']['data']['parent_item']['material_code'] == 'ENTERPRISE-A'
    assert '不是最新库存重查' in response['answer']
    assert not service.repository.get_session(session)['context'].get('last_query_failure')
