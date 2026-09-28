<script setup>
import { computed, ref } from 'vue'
import { ApiError, chatPmc, getChatHistory } from '../api/pmc'

const message = ref('我要生产100台KQ-Z112，帮我看看能不能开工')
const messages = ref([
  { role: 'agent', content: '请用自然语言描述生产任务，例如：我要生产100台KQ-Z112。' },
])
const result = ref(null)
const errorMessage = ref('')
const isSending = ref(false)
const conversationWorkflowId = ref(null)
const sessionHistory = ref([])
const pendingStatuses = ['正在解析任务...', '正在分析 BOM...', '正在计算库存...', '正在检查采购...', '正在生成生产方案...']
const demoCases = [
  { label: '单台开工分析', message: '我要生产1台KQ-Z112，帮我看看能不能开工' },
  { label: '100台批量评估', message: '我要生产100台KQ-Z112，帮我看看能不能开工' },
]

const decisionLabel = computed(() => ({
  ready: '可开工',
  blocked: '生产受阻',
  procurement_pending: '采购待到货',
  data_incomplete: '数据不完整',
}[result.value?.decision_status] || '等待分析'))

async function sendMessage(candidateMessage = message.value) {
  const userMessage = candidateMessage.trim()
  if (!userMessage || isSending.value) return

  errorMessage.value = ''
  result.value = null
  messages.value.push({ role: 'user', content: userMessage })
  const pendingMessage = { role: 'agent', content: '正在理解当前任务并准备执行 PMC 工作流。', pending: true }
  messages.value.push(pendingMessage)
  isSending.value = true
  try {
    const response = await chatPmc(userMessage, conversationWorkflowId.value)
    conversationWorkflowId.value = response.conversation_workflow_id
    sessionHistory.value = (await getChatHistory(response.conversation_workflow_id)).history
    if (response.turn_type === 'analysis') {
      messages.value.push({
        role: 'agent',
        content: `已理解生产任务：产品 ${response.parsed_task.product}，BOM ${response.parsed_task.bom_version}，数量 ${response.parsed_task.quantity}。`,
      })
    } else if (response.turn_type === 'scenario') {
      messages.value.push({
        role: 'agent',
        content: `已复用当前会话，将备选生产数量调整为 ${response.parsed_task.quantity} 台。`,
      })
    }
    result.value = response
    messages.value.push({
      role: 'agent',
      content: `${response.turn_type === 'explanation' ? '说明完成' : '处理完成'}：${decisionLabel.value}（${response.workflow_status}）。${response.agent_message}`,
    })
    response.follow_up_questions.forEach((question) => messages.value.push({ role: 'agent', content: question }))
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '无法连接 PMC API。'
    const followUp = error instanceof ApiError && error.status === 422
      ? '请补充产品型号和生产数量后再试，例如：我要生产100台KQ-Z112。'
      : '请检查输入或稍后重试。'
    messages.value.push({ role: 'agent', content: `无法执行分析：${errorMessage.value}\n${followUp}` })
  } finally {
    messages.value = messages.value.filter((item) => item !== pendingMessage)
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

      <div class="demo-cases" aria-label="演示案例">
        <span>Demo 案例</span>
        <button v-for="item in demoCases" :key="item.label" type="button" :disabled="isSending" @click="message = item.message; sendMessage(item.message)">
          {{ item.label }}
        </button>
      </div>

      <div v-if="isSending" class="agent-status" aria-live="polite">
        <strong>Agent 执行状态</strong>
        <span v-for="item in pendingStatuses" :key="item">{{ item }}</span>
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
      <p v-if="conversationWorkflowId" class="session-hint">当前会话：{{ conversationWorkflowId }} · 已同步 {{ sessionHistory.length }} 条会话记录</p>
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
        <h2>Agent 执行过程</h2>
        <p class="trace-note">展示的是工具调用状态，不展示模型思维链、提示词或内部工作流 State。</p>
        <ol class="execution-trace">
          <li v-for="step in result.agent_trace" :key="`${step.step}-${step.status}`" :data-status="step.status">
            <strong>{{ step.step }}</strong><code>{{ step.status }}</code><span>{{ step.summary }}</span>
          </li>
        </ol>
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

      <section v-if="result.scenario" class="panel scenario-panel">
        <h2>方案比较</h2>
        <article class="scenario-card original-scenario">
          <span>原方案 · {{ result.scenario.original_result.report.product_information?.production_quantity }} 台</span>
          <strong>{{ result.scenario.original_result.decision_status }}</strong>
          <small>工作流：{{ result.scenario.original_result.workflow_status }}</small>
        </article>
        <article class="scenario-card">
          <span>备选方案 · {{ result.scenario.quantity }} 台</span>
          <strong>{{ result.scenario.workflow_result.decision_status }}</strong>
          <small>{{ result.scenario.improvement }}</small>
        </article>
      </section>

      <section v-if="result.follow_up_questions.length" class="panel follow-up-panel">
        <h2>Agent 主动追问</h2>
        <p>以下信息缺失，系统不会自行编造采购参数。</p>
        <ul class="action-list"><li v-for="question in result.follow_up_questions" :key="question">{{ question }}</li></ul>
      </section>
    </template>
  </section>
</template>
