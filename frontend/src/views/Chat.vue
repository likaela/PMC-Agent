<script setup>
import { computed, ref } from 'vue'
import { ApiError, chatPmc } from '../api/pmc'

const message = ref('我要生产100台KQ-Z112，帮我看看能不能开工')
const messages = ref([
  { role: 'agent', content: '请用自然语言描述生产任务，例如：我要生产100台KQ-Z112。' },
])
const result = ref(null)
const errorMessage = ref('')
const isSending = ref(false)

const decisionLabel = computed(() => ({
  ready: '可开工',
  blocked: '生产受阻',
  procurement_pending: '采购待到货',
  data_incomplete: '数据不完整',
}[result.value?.decision_status] || '等待分析'))

async function sendMessage() {
  const userMessage = message.value.trim()
  if (!userMessage || isSending.value) return

  errorMessage.value = ''
  result.value = null
  messages.value.push({ role: 'user', content: userMessage })
  isSending.value = true
  try {
    const response = await chatPmc(userMessage)
    messages.value.push({
      role: 'agent',
      content: `已理解生产任务：产品 ${response.parsed_task.product}，BOM ${response.parsed_task.bom_version}，数量 ${response.parsed_task.quantity}。正在执行 PMC 分析。`,
    })
    result.value = response
    messages.value.push({
      role: 'agent',
      content: `分析完成：${decisionLabel.value}（${response.workflow_status}）。`,
    })
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '无法连接 PMC API。'
    messages.value.push({ role: 'agent', content: `无法执行分析：${errorMessage.value}` })
  } finally {
    isSending.value = false
  }
}
</script>

<template>
  <section class="chat-layout">
    <section class="panel chat-panel">
      <div class="section-heading">
        <div>
          <h2>自然语言 PMC Agent</h2>
          <p>仅理解任务参数；库存、缺料、采购和生产结论全部来自后端确定性工作流。</p>
        </div>
      </div>

      <div class="chat-history" aria-live="polite">
        <article v-for="(item, index) in messages" :key="index" class="chat-bubble" :class="item.role">
          <strong>{{ item.role === 'user' ? '用户' : 'Agent' }}</strong>
          <p>{{ item.content }}</p>
        </article>
      </div>

      <form class="chat-composer" @submit.prevent="sendMessage">
        <label>生产任务<input v-model="message" :disabled="isSending" placeholder="例如：我要生产100台KQ-Z112" /></label>
        <button type="submit" :disabled="isSending">{{ isSending ? '正在分析…' : '发送并分析' }}</button>
      </form>
      <p v-if="errorMessage" class="message error">{{ errorMessage }}</p>
    </section>

    <template v-if="result">
      <section class="status-grid">
        <article class="status-card" :data-status="result.decision_status || 'unknown'">
          <span>生产决策</span><strong>{{ decisionLabel }}</strong><small>{{ result.decision_status || '未返回' }}</small>
        </article>
        <article class="status-card"><span>Agent 执行状态</span><strong>{{ result.workflow_status }}</strong><small>workflow_id: {{ result.workflow_id }}</small></article>
        <article class="status-card"><span>是否可开工</span><strong>{{ result.can_start_production === true ? '是' : result.can_start_production === false ? '否' : '待确认' }}</strong><small>来自 Production Decision</small></article>
        <article class="status-card"><span>待补采购参数</span><strong>{{ result.missing_purchase_parameters.length }}</strong><small>来自 API 返回清单</small></article>
      </section>

      <section class="panel">
        <h2>缺料与阻塞物料</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>优先级</th><th>物料</th><th>需求</th><th>可用</th><th>缺料</th><th>采购状态</th><th>风险</th></tr></thead>
            <tbody>
              <tr v-for="item in result.blocking_materials" :key="item.material">
                <td>P{{ item.priority }}</td><td>{{ item.material }}</td><td>{{ item.required }}</td><td>{{ item.available ?? '—' }}</td><td>{{ item.shortage }}</td><td>{{ item.purchase_status }}</td><td>{{ item.risk_level || '待补参数' }}</td>
              </tr>
              <tr v-if="!result.blocking_materials.length"><td colspan="7" class="empty">API 未返回阻塞物料。</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="result.report.production_decision?.recommended_actions?.length" class="panel">
        <h2>建议行动</h2>
        <ul class="action-list">
          <li v-for="action in result.report.production_decision.recommended_actions" :key="`${action.priority}-${action.material}-${action.action}`">
            P{{ action.priority }} {{ action.material || '全部相关物料' }}：{{ action.action }}
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>
