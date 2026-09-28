<script setup>
import { computed, onMounted, ref } from 'vue'
import { ApiError, chatPmc, getChatHistory, getDemoCases, getDemoStatistics, submitDemoFeedback } from '../api/pmc'
import WorkflowTrace from '../components/WorkflowTrace.vue'

const message = ref('我要生产100台KQ-Z112，帮我看看能不能开工')
const messages = ref([
  { role: 'agent', content: '请用自然语言描述生产任务，例如：我要生产100台KQ-Z112。' },
])
const result = ref(null)
const taskUnderstanding = ref(null)
const errorMessage = ref('')
const isSending = ref(false)
const conversationWorkflowId = ref(null)
const sessionHistory = ref([])
const feedback = ref('')
const feedbackMessage = ref('')
const isSubmittingFeedback = ref(false)
const demoStatistics = ref(null)
const demoCases = ref([
  { id: 'analyze-100', label: '我要生产100台KQ-Z112', message: '我要生产100台KQ-Z112，帮我分析', requires_workflow: false },
  { id: 'why-blocked', label: '为什么不能生产？', message: '为什么不能生产？', requires_workflow: true },
  { id: 'reduce-50', label: '如果减少到50台呢？', message: '如果减少到50台呢？', requires_workflow: true },
  { id: 'production-impact', label: '哪些物料最影响生产？', message: '哪些物料最影响生产？', requires_workflow: true },
])

function decisionStatusLabel(status) {
  return ({
  ready: '可开工',
  blocked: '生产受阻',
  procurement_pending: '采购待到货',
  data_incomplete: '数据不完整',
  }[status] || '等待分析')
}

function workflowStatusLabel(status) {
  return ({
    waiting_for_purchase_parameters: '等待补充采购参数',
    completed: '分析完成',
    running: '正在分析',
    error: '分析暂不可用',
  }[status] || '状态待确认')
}

const decisionLabel = computed(() => decisionStatusLabel(result.value?.decision_status))

const demoJourney = computed(() => {
  const completedTurns = new Set(sessionHistory.value.map((item) => item.turn_type))
  return [
    { label: '首次生产分析', state: conversationWorkflowId.value ? 'completed' : 'pending' },
    { label: '原因追问', state: completedTurns.has('explanation') ? 'completed' : 'pending' },
    { label: '产量调整', state: completedTurns.has('scenario') ? 'completed' : 'pending' },
    { label: '重新方案', state: result.value?.scenario ? 'completed' : 'pending' },
  ]
})

function parserSourceLabel(source) {
  return source === 'llm' ? 'DeepSeek' : 'Rule fallback'
}

async function refreshDemoStatistics() {
  try {
    demoStatistics.value = await getDemoStatistics()
  } catch {
    // Demo 统计不可用不应阻塞生产分析。
  }
}

function runDemoCase(item) {
  if (item.requires_workflow && !conversationWorkflowId.value) {
    errorMessage.value = '请先运行“我要生产100台KQ-Z112”，再进行原因、方案或阻塞物料追问。'
    return
  }
  message.value = item.message
  sendMessage(item.message)
}

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
    if (response.response_type === 'clarification') {
      taskUnderstanding.value = response.task_intent
      messages.value.push({
        role: 'agent',
        content: response.agent_message,
      })
      return
    }
    conversationWorkflowId.value = response.conversation_workflow_id
    sessionHistory.value = (await getChatHistory(response.conversation_workflow_id)).history
    await refreshDemoStatistics()
    if (response.turn_type === 'analysis') {
      const understood = response.task_intent || response.parsed_task
      taskUnderstanding.value = response.task_intent || null
      const sourceLabel = response.task_intent ? parserSourceLabel(response.task_intent.parser_source) : 'Rule fallback'
      messages.value.push({
        role: 'agent',
        content: `AI 已识别任务：产品 ${understood.product}，BOM ${understood.bom_version}，数量 ${understood.quantity}。解析来源：${sourceLabel}。`,
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
      content: `${response.turn_type === 'explanation' ? '说明完成' : '处理完成'}：${decisionLabel.value}。${response.agent_message}`,
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

async function submitFeedback() {
  const content = feedback.value.trim()
  if (!content || !conversationWorkflowId.value || isSubmittingFeedback.value) return

  feedbackMessage.value = ''
  isSubmittingFeedback.value = true
  try {
    const response = await submitDemoFeedback(conversationWorkflowId.value, content)
    feedbackMessage.value = response.message
    feedback.value = ''
    await refreshDemoStatistics()
  } catch (error) {
    feedbackMessage.value = error instanceof ApiError ? error.message : '反馈提交失败，请稍后重试。'
  } finally {
    isSubmittingFeedback.value = false
  }
}

onMounted(async () => {
  try {
    demoCases.value = (await getDemoCases()).cases
  } catch {
    // 保留本地默认案例，使 API 暂不可用时仍可阅读 Demo 引导。
  }
  await refreshDemoStatistics()
})
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

      <section class="demo-onboarding">
        <h3>欢迎体验 PMC-Agent Demo</h3>
        <p>这是一个面向制造业 PMC 的生产决策助手：理解生产任务后，由后端确定性工作流完成 BOM、库存、缺料、采购与生产决策分析。</p>
        <div class="guide-grid">
          <article><strong>可以解决什么</strong><span>判断是否可开工、定位阻塞物料、提示待补采购参数、比较减量方案。</span></article>
          <article><strong>当前支持能力</strong><span>KQ-Z112 / V01 演示、连续追问、公开节点 Trace 与当前进程内方案推演。</span></article>
          <article><strong>推荐流程</strong><span>先分析 100 台 → 追问原因 → 查看关键物料 → 推演减少到 50 台。</span></article>
        </div>
      </section>

      <div class="demo-cases" aria-label="演示案例">
        <span>Demo 案例</span>
        <button v-for="item in demoCases" :key="item.id" type="button" :disabled="isSending" @click="runDemoCase(item)">
          {{ item.label }}
        </button>
      </div>

      <section v-if="demoStatistics" class="demo-statistics" aria-label="Demo 当前进程统计">
        <span>当前进程体验：{{ demoStatistics.total_experience_count }} 次</span>
        <span>成功分析：{{ demoStatistics.successful_analysis_count }} 次</span>
        <span>方案推演：{{ demoStatistics.scenario_count }} 次</span>
      </section>

      <WorkflowTrace :steps="result?.agent_trace || []" :loading="isSending" />

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

      <section v-if="taskUnderstanding" class="panel task-understanding">
        <h2>AI 解析结果</h2>
        <dl class="task-details">
          <div><dt>产品</dt><dd>{{ taskUnderstanding.product || '待补充' }}</dd></div>
          <div><dt>数量</dt><dd>{{ taskUnderstanding.quantity === null ? '待补充' : taskUnderstanding.quantity }}</dd></div>
          <div><dt>BOM 版本</dt><dd>{{ taskUnderstanding.bom_version || '待补充' }}</dd></div>
          <div><dt>解析来源</dt><dd>{{ parserSourceLabel(taskUnderstanding.parser_source) }}</dd></div>
        </dl>
        <p v-if="taskUnderstanding.missing_fields.length" class="missing-task-fields">需要补充：{{ taskUnderstanding.missing_fields.join('、') }}</p>
      </section>

      <section class="demo-journey" aria-label="完整 Demo 演示流程">
        <span>推荐 Demo 流程</span>
        <ol>
          <li v-for="(step, index) in demoJourney" :key="step.label" :data-state="step.state">
            <b>{{ index + 1 }}</b>{{ step.label }}
          </li>
        </ol>
      </section>
    </section>

    <template v-if="result">
      <section class="status-grid">
        <article class="status-card" :data-status="result.decision_status || 'unknown'">
          <span>生产决策</span><strong>{{ decisionLabel }}</strong><small>由确定性生产决策服务生成</small>
        </article>
        <article class="status-card"><span>Agent 执行状态</span><strong>{{ workflowStatusLabel(result.workflow_status) }}</strong><small>本次分析已关联当前会话</small></article>
        <article class="status-card"><span>是否可开工</span><strong>{{ result.can_start_production === true ? '是' : result.can_start_production === false ? '否' : '待确认' }}</strong><small>来自 Production Decision</small></article>
        <article class="status-card"><span>待补采购参数</span><strong>{{ result.missing_purchase_parameters.length }}</strong><small>来自 API 返回清单</small></article>
      </section>

      <section v-if="result.explanation" class="panel explanation-panel">
        <h2>PMC 结果解释</h2>
        <p>{{ result.explanation.answer }}</p>
        <small>解释来源：{{ result.explanation.source === 'llm' ? 'DeepSeek' : '确定性模板' }}</small>
      </section>

      <section class="decision-summary-grid">
        <article class="panel decision-summary-card feasibility-card" :data-status="result.decision_status || 'unknown'">
          <span>生产可行性</span>
          <strong>{{ result.can_start_production === true ? '可以开工' : result.can_start_production === false ? '暂不可开工' : '待确认' }}</strong>
          <p>{{ decisionLabel }} · {{ workflowStatusLabel(result.workflow_status) }}</p>
        </article>
        <article class="panel decision-summary-card risk-card">
          <span>风险因素</span>
          <ul v-if="result.report.production_decision?.decision_reasons?.length">
            <li v-for="reason in result.report.production_decision.decision_reasons" :key="reason">{{ reason }}</li>
          </ul>
          <p v-else>当前报告未返回额外风险原因。</p>
        </article>
        <article class="panel decision-summary-card action-card">
          <span>建议动作</span>
          <ul v-if="result.report.production_decision?.recommended_actions?.length">
            <li v-for="action in result.report.production_decision.recommended_actions" :key="`${action.priority}-${action.material}-${action.action}`">
              {{ action.action }}
            </li>
          </ul>
          <p v-else>当前报告未返回建议动作。</p>
        </article>
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
          <strong>{{ decisionStatusLabel(result.scenario.original_result.decision_status) }}</strong>
          <small>{{ workflowStatusLabel(result.scenario.original_result.workflow_status) }}</small>
        </article>
        <article class="scenario-card">
          <span>备选方案 · {{ result.scenario.quantity }} 台</span>
          <strong>{{ decisionStatusLabel(result.scenario.workflow_result.decision_status) }}</strong>
          <small>{{ result.scenario.improvement }}</small>
        </article>
      </section>

      <section v-if="result.follow_up_questions.length" class="panel follow-up-panel">
        <h2>Agent 主动追问</h2>
        <p>以下信息缺失，系统不会自行编造采购参数。</p>
        <ul class="action-list"><li v-for="question in result.follow_up_questions" :key="question">{{ question }}</li></ul>
      </section>

      <section class="panel feedback-panel">
        <h2>体验反馈</h2>
        <p>反馈仅保存在当前服务进程，用于本轮小范围体验测试；不会保存 Excel、BOM、库存或其他原始企业数据。</p>
        <form class="feedback-form" @submit.prevent="submitFeedback">
          <label>你的反馈<textarea v-model="feedback" :disabled="isSubmittingFeedback" maxlength="1000" placeholder="例如：阻塞物料说明是否清晰？"></textarea></label>
          <button type="submit" :disabled="isSubmittingFeedback || !feedback.trim()">{{ isSubmittingFeedback ? '正在提交…' : '提交反馈' }}</button>
        </form>
        <p v-if="feedbackMessage" class="message success">{{ feedbackMessage }}</p>
      </section>
    </template>
  </section>
</template>
