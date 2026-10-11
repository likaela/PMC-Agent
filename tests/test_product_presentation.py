"""Copy-only changes preserve existing Tool/Evidence and scope semantics."""
import re

from tests.test_reviewer_default_scope import filtered
from tests.test_authorized_review import new, ask
from tests.test_slim_review_scenario import selected
from tests.test_enterprise_book_analysis import book
from tests.test_published_bom_business_confirmation import fixture


def test_business_scope_labels_and_answers_preserve_facts(filtered):
    _, client = filtered
    catalog = client.get('/api/v1/review/catalog').json()['products']
    assert [s['label'] for s in catalog[0]['modes']] == ['标准分析范围', '完整追溯范围']
    result = ask(client, new(client), '生产1片可以吗？').json()
    data = result['structured_data']['data']
    assert data['inventory_sufficient_for_requested'] is True
    assert '当前分析范围：' in result['answer']
    assert '不代表完整产品生产放行' in result['answer']
    assert not re.search(r'保留\d+项|排除\d+项|没有合成补充|精简评审', result['answer'])
    assert data['original_material_count'] == 66  # Private scope audit remains intact.


def test_new_scope_phrase_resolves_existing_modes_and_catalog_truth(filtered):
    _, client = filtered
    result = client.post('/api/v1/review/resolve', json={'message':'切换到标准分析范围'}).json()
    assert result['analysis_mode'] == 'slim'
    result = client.post('/api/v1/review/resolve', json={'message':'切换到完整追溯范围'}).json()
    assert result['analysis_mode'] == 'full'
    reply = ask(client, new(client), '已发布BOM的产品有哪些？').json()
    assert len(reply['structured_data']['data']['products']) == 3
    assert 'DEMO-PMC-01（演示产品）' in reply['answer']
    assert '真实企业产品' not in reply['answer'] and '合成演示' not in reply['answer']
