<script setup>
import { computed, onMounted, ref } from 'vue'
import { ApiError, chatPmc, getChatHistory, getDemoStatistics, getPmcWorkflow, submitDemoFeedback } from '../api/pmc'
import DemoGuide from '../components/DemoGuide.vue'
import WorkflowTrace from '../components/WorkflowTrace.vue'
import { normalizeCandidateMessage } from '../utils/chatMessage'
import { clearDemoSession, loadDemoSession, saveDemoSession } from '../utils/demoSession'
import {
  formatAgentMessage,
  formatHistoryMessage,
  formatScenarioImprovement,
  getMaterialPresentation,
  getPresentedActions,
  getPresentedMaterials,
  getVisibleFollowUpQuestions,
  hasLoadedDemoPurchaseParameters,
  presentationRiskLabel,
} from '../utils/presentation'

const DEFAULT_DEMO_MESSAGE = '我要生产100台KQ-Z112，帮我看看能不能开工'
const message = ref(DEFAULT_DEMO_MESSAGE)
const messages = ref(createInitialMessages())
const result = ref(null)
const taskUnderstanding = ref(null)
const errorMessage = ref('')
const isSending = ref(false)
const conversationWorkflowId = ref(null)
const activeWorkflowId = ref(null)
const sessionHistory = ref([])
const feedback = ref('')
const feedbackMessage = ref('')
const isSubmittingFeedback = ref(false)
const demoStatistics = ref(null)
const retryRequest = ref(null)
const isFullDemoActive = ref(false)
const completedDemoStep = ref(0)
const quickExperienceCases = [
  { id: 'analyze-100', label: '我要生产100台KQ-Z112', message: '我要生产100台KQ-Z112', requires_workflow: false },
  { id: 'why-blocked', label: '为什么不能生产？', message: '为什么不能生产？', requires_workflow: true },
  { id: 'reduce-50', label: '减少到50台呢？', message: '减少到50台呢？', requires_workflow: true },
]
const fullDemoSteps = [
  { label: '分析 100 台 KQ-Z112', message: '我要生产100台KQ-Z112', requiresWorkflow: false },
  { label: '追问无法生产原因', message: '为什么不能生产？', requiresWorkflow: true },
  { label: '推演 50 台备选方案', message: '减少到50台呢？', requiresWorkflow: true },
  { label: '查看关键物料', message: '哪些物料影响最大？', requiresWorkflow: true },
]

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
    waiting_for_purchase_parameters: '采购信息待补充',
    completed: '分析完成',
    running: '正在分析',
    error: '分析暂不可用',
  }[status] || '状态待确认')
}

const decisionLabel = computed(() => decisionStatusLabel(result.value?.decision_status))
const hasReport = computed(() => Boolean(result.value?.report && Object.keys(result.value.report).length))
const hasBlockingMaterials = computed(() => Array.isArray(result.value?.blocking_materials) && result.value.blocking_materials.length > 0)
const presentedBlockingMaterials = computed(() => getPresentedMaterials(result.value?.blocking_materials))
const remainingBlockingMaterialCount = computed(() => Math.max(
  (result.value?.blocking_materials?.length || 0) - presentedBlockingMaterials.value.length,
  0,
))
const demoPurchaseParametersLoaded = computed(() => hasLoadedDemoPurchaseParameters(result.value))
const visibleFollowUpQuestions = computed(() => getVisibleFollowUpQuestions(result.value))
const presentedRecommendedActions = computed(() => getPresentedActions(
  result.value?.report?.production_decision?.recommended_actions,
  result.value?.blocking_materials,
))
const hasRecommendedActions = computed(() => presentedRecommendedActions.value.length > 0)
const formattedExplanation = computed(() => formatAgentMessage(result.value))
const currentPlanLabel = computed(() => {
  const task = result.value?.parsed_task
  return task?.product && Number.isInteger(task?.quantity)
    ? `当前分析方案：${task.quantity} 台 ${task.product}`
    : '当前分析方案待确认'
})
const productionStatusLabel = computed(() => ({
  ready: '可生产',
  procurement_pending: '风险生产',
  data_incomplete: '风险生产',
  blocked: '无法生产',
}[result.value?.decision_status] || '待确认'))

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
  if (source === 'llm') return 'DeepSeek'
  if (source === 'restored') return '已恢复会话'
  return '本地规则回退'
}

function materialPresentation(item, index) {
  return getMaterialPresentation(item, index)
}

function actionMaterialLabel(action) {
  if (!action?.material) return '全部相关物料'
  const index = result.value?.blocking_materials?.findIndex((item) => item.material === action.material) ?? -1
  return getMaterialPresentation({ material: action.material }, index >= 0 ? index : 0).label
}

function createInitialMessages() {
  return [{ role: 'agent', content: '我是面向制造企业的生产决策智能体。请告诉我产品型号和生产数量，例如：我要生产100台KQ-Z112。' }]
}

function resetDemoSession({ notice = '' } = {}) {
  clearDemoSession(window.sessionStorage)
  conversationWorkflowId.value = null
  activeWorkflowId.value = null
  sessionHistory.value = []
  result.value = null
  taskUnderstanding.value = null
  errorMessage.value = ''
  feedback.value = ''
  feedbackMessage.value = ''
  retryRequest.value = null
  isFullDemoActive.value = false
  completedDemoStep.value = 0
  messages.value = createInitialMessages()
  if (notice) messages.value.push({ role: 'agent', content: notice })
}

function restartDemo() {
  resetDemoSession({ notice: '已重新开始分析。请输入新的生产任务，或点击下方 Demo 案例。' })
  message.value = DEFAULT_DEMO_MESSAGE
}

function persistDemoSession(response) {
  if (!response?.workflow_id || !response?.conversation_workflow_id || !response?.parsed_task) return
  saveDemoSession(window.sessionStorage, {
    workflow_id: response.workflow_id,
    session_id: response.conversation_workflow_id,
    task_summary: response.parsed_task,
  })
}

function isUsableAnalysisResponse(response) {
  return Boolean(
    response
    && response.response_type !== 'clarification'
    && typeof response.workflow_id === 'string'
    && typeof response.conversation_workflow_id === 'string'
    && Array.isArray(response.blocking_materials)
    && Array.isArray(response.missing_purchase_parameters)
    && response.report
    && typeof response.report === 'object',
  )
}

function userFacingError(error) {
  if (error instanceof ApiError) return error.message
  return '分析服务暂时异常，请稍后重试。'
}

function isNewProductionRequest(text) {
  const isFollowUp = /为什么|为何|原因|哪些物料最影响生产|哪些物料影响最大|哪些物料影响生产|哪些物料最关键|哪些材料影响最大|最影响生产|减少到|改为|调整为/.test(text)
  return !isFollowUp && /生产|安排|计划|做/.test(text)
}

async function refreshDemoStatistics() {
  try {
    demoStatistics.value = await getDemoStatistics()
  } catch {
    // Demo 统计不可用不应阻塞生产分析。
  }
}

function runDemoCase(item) {
  isFullDemoActive.value = false
  completedDemoStep.value = 0
  if (item.requires_workflow && !conversationWorkflowId.value) {
    errorMessage.value = '请先运行“我要生产100台KQ-Z112”，再进行原因、方案或阻塞物料追问。'
    return
  }
  if (!item.requires_workflow) {
    resetDemoSession()
  }
  message.value = item.message
  sendMessage(item.message, { reuseCurrentWorkflow: item.requires_workflow })
}

function startFullDemo() {
  resetDemoSession()
  isFullDemoActive.value = true
  continueFullDemo()
}

function continueFullDemo() {
  const step = fullDemoSteps[completedDemoStep.value]
  if (!step || isSending.value) return
  message.value = step.message
  sendMessage(step.message, {
    reuseCurrentWorkflow: step.requiresWorkflow,
    demoStep: completedDemoStep.value + 1,
  })
}

async function sendMessage(candidateMessage = message.value, { reuseCurrentWorkflow = true, demoStep = null } = {}) {
  const messageText = normalizeCandidateMessage(candidateMessage)
  const userMessage = messageText.trim()
  if (!userMessage || isSending.value) return

  const shouldReuseWorkflow = reuseCurrentWorkflow
    && Boolean(activeWorkflowId.value)
    && !isNewProductionRequest(userMessage)
  if (!shouldReuseWorkflow && conversationWorkflowId.value) {
    resetDemoSession()
  }

  errorMessage.value = ''
  result.value = null
  retryRequest.value = { message: userMessage, reuseCurrentWorkflow: shouldReuseWorkflow, demoStep }
  messages.value.push({ role: 'user', content: userMessage })
  const pendingMessage = { role: 'agent', content: '正在理解生产需求，并准备开展物料、库存与采购分析。', pending: true }
  messages.value.push(pendingMessage)
  isSending.value = true
  try {
    const response = await chatPmc(userMessage, shouldReuseWorkflow ? activeWorkflowId.value : null)
    if (response.response_type === 'clarification') {
      taskUnderstanding.value = response.task_intent
      messages.value.push({
        role: 'agent',
        content: formatAgentMessage(response),
      })
      return
    }
    if (!isUsableAnalysisResponse(response)) {
      throw new ApiError('分析服务暂时异常，请稍后重试。', 500, 'ANALYSIS_UNAVAILABLE')
    }
    conversationWorkflowId.value = response.conversation_workflow_id
    activeWorkflowId.value = response.workflow_id
    sessionHistory.value = (await getChatHistory(response.conversation_workflow_id)).history
    persistDemoSession(response)
    await refreshDemoStatistics()
    if (response.turn_type === 'analysis') {
      const understood = response.task_intent || response.parsed_task
      taskUnderstanding.value = response.task_intent || null
      const sourceLabel = response.task_intent ? parserSourceLabel(response.task_intent.parser_source) : '本地规则解析'
      messages.value.push({
        role: 'agent',
        content: `AI 已识别任务：产品 ${understood.product}，BOM ${understood.bom_version}，数量 ${understood.quantity}。解析来源：${sourceLabel}。`,
      })
    }
    result.value = response
    if (demoStep !== null) completedDemoStep.value = demoStep
    retryRequest.value = null
    if (hasLoadedDemoPurchaseParameters(response) && ['analysis', 'scenario'].includes(response.turn_type)) {
      messages.value.push({
        role: 'agent',
        content: '已加载演示采购参数，采购建议已生成。',
      })
    }
    messages.value.push({
      role: 'agent',
      content: formatAgentMessage(response),
    })
    getVisibleFollowUpQuestions(response).forEach((question) => messages.value.push({ role: 'agent', content: question }))
  } catch (error) {
    const sessionExpired = error instanceof ApiError && error.code === 'SESSION_EXPIRED'
    if (sessionExpired) {
      resetDemoSession({ notice: '当前演示会话已失效，请重新开始分析。' })
      message.value = DEFAULT_DEMO_MESSAGE
      return
    }
    errorMessage.value = userFacingError(error)
    const followUp = error instanceof ApiError && error.code === 'INVALID_REQUEST'
      ? '请补充产品型号和生产数量后再试，例如：我要生产100台KQ-Z112。'
      : '你可以重试本次请求，或重新开始分析。'
    messages.value.push({ role: 'agent', content: `无法执行分析：${errorMessage.value}\n${followUp}` })
  } finally {
    messages.value = messages.value.filter((item) => item !== pendingMessage)
    isSending.value = false
  }
}

function retryLastRequest() {
  if (!retryRequest.value || isSending.value) return
  sendMessage(retryRequest.value.message, {
    reuseCurrentWorkflow: retryRequest.value.reuseCurrentWorkflow,
    demoStep: retryRequest.value.demoStep,
  })
}

async function restoreDemoSession() {
  const saved = loadDemoSession(window.sessionStorage)
  if (!saved) {
    clearDemoSession(window.sessionStorage)
    return
  }
  try {
    const [workflow, historyResponse] = await Promise.all([
      getPmcWorkflow(saved.workflow_id),
      getChatHistory(saved.session_id),
    ])
    if (!workflow?.report || typeof workflow.report !== 'object' || !Array.isArray(historyResponse?.history)) {
      throw new ApiError('当前演示会话已失效，请重新开始分析。', 404, 'SESSION_EXPIRED')
    }
    conversationWorkflowId.value = saved.session_id
    activeWorkflowId.value = saved.workflow_id
    sessionHistory.value = historyResponse.history
    taskUnderstanding.value = {
      ...saved.task_summary,
      missing_fields: [],
      parser_source: 'restored',
    }
    const restoredContext = {
      ...workflow,
      parsed_task: saved.task_summary,
    }
    messages.value = historyResponse.history.map((item) => ({
      role: item.role,
      content: formatHistoryMessage(item, restoredContext),
    }))
    result.value = {
      ...workflow,
      conversation_workflow_id: saved.session_id,
      parsed_task: saved.task_summary,
      agent_trace: workflow.execution_steps || [],
      follow_up_questions: [],
      scenario: null,
      explanation: null,
    }
    message.value = `为什么不能生产？`
  } catch {
    resetDemoSession({ notice: '当前演示会话已失效，请重新开始分析。' })
    message.value = DEFAULT_DEMO_MESSAGE
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
  await refreshDemoStatistics()
  await restoreDemoSession()
})
</script>

<template>
  <section class="chat-layout">
    <section class="panel chat-panel">
      <section class="agent-hero">
        <div>
          <span>智造 PMC Agent</span>
          <h2>面向制造企业的生产决策智能体</h2>
          <p>用户只需描述生产需求，Agent 即可自动理解任务，并依次完成物料、库存、采购与生产可行性分析。</p>
        </div>
        <ol class="agent-flow" aria-label="生产决策流程">
          <li>需求理解</li><li>物料分析</li><li>库存检查</li><li>采购建议</li><li>生产决策</li>
        </ol>
      </section>

      <section class="demo-onboarding">
        <h3>欢迎体验制造生产决策 Agent</h3>
        <p>直接输入产品和数量即可开始分析，也可以在首轮结果后继续追问原因、调整数量或查看关键物料。</p>
        <div class="guide-grid">
          <article><strong>可以解决什么</strong><span>判断是否可开工、定位阻塞物料、生成采购建议、比较减量方案。</span></article>
          <article><strong>当前支持能力</strong><span>KQ-Z112 / V01 演示、连续追问、分析进度展示与生产方案调整。</span></article>
          <article><strong>推荐流程</strong><span>先分析 100 台 → 追问原因 → 查看关键物料 → 推演减少到 50 台。</span></article>
        </div>
      </section>

      <div class="demo-cases quick-experience" aria-label="快速体验">
        <span>快速体验</span>
        <button v-for="item in quickExperienceCases" :key="item.id" type="button" :disabled="isSending" @click="runDemoCase(item)">
          {{ item.label }}
        </button>
        <button class="secondary-button" type="button" :disabled="isSending" @click="restartDemo">重新开始分析</button>
      </div>

      <DemoGuide
        :active="isFullDemoActive"
        :completed-step="completedDemoStep"
        :loading="isSending"
        :steps="fullDemoSteps"
        @start="startFullDemo"
        @continue="continueFullDemo"
      />

      <section v-if="demoStatistics" class="demo-statistics" aria-label="Demo 当前进程统计">
        <span>本次体验：{{ demoStatistics.total_experience_count }} 次</span>
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

      <form class="chat-composer" @submit.prevent="sendMessage(message)">
        <label>生产任务<input v-model="message" :disabled="isSending" placeholder="例如：我要生产100台KQ-Z112" /></label>
        <button type="submit" :disabled="isSending">{{ isSending ? '正在分析…' : '发送并分析' }}</button>
      </form>
      <p v-if="errorMessage" class="message error">{{ errorMessage }}</p>
      <button v-if="retryRequest" class="retry-button" type="button" :disabled="isSending" @click="retryLastRequest">
        重试本次请求
      </button>
      <p v-if="conversationWorkflowId" class="session-hint">当前演示会话已恢复 · 已同步 {{ sessionHistory.length }} 条会话记录</p>

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
      <p class="current-plan-label">{{ currentPlanLabel }}</p>
      <section class="status-grid">
        <article class="status-card" :data-status="result.decision_status || 'unknown'">
          <span>生产状态</span><strong>{{ productionStatusLabel }}</strong><small>{{ decisionLabel }} · 由生产决策分析生成</small>
        </article>
        <article class="status-card"><span>Agent 执行状态</span><strong>{{ workflowStatusLabel(result.workflow_status) }}</strong><small>本次分析已关联当前会话</small></article>
        <article class="status-card"><span>是否可开工</span><strong>{{ result.can_start_production === true ? '是' : result.can_start_production === false ? '否' : '待确认' }}</strong><small>来自生产可行性分析</small></article>
        <article class="status-card">
          <span>{{ demoPurchaseParametersLoaded ? '演示采购参数' : '待补采购参数' }}</span>
          <strong>{{ demoPurchaseParametersLoaded ? '已加载' : result.missing_purchase_parameters.length }}</strong>
          <small>{{ demoPurchaseParametersLoaded ? '已生成确定性采购建议' : '来自 API 返回清单' }}</small>
        </article>
      </section>

      <section v-if="!hasReport" class="panel empty-result-panel">
        <h2>暂无可展示结果</h2>
        <p>{{ result.public_error?.user_message || '暂无可展示结果，请重新分析或稍后重试。' }}</p>
        <button type="button" @click="restartDemo">重新开始分析</button>
      </section>

      <section v-if="hasReport && result.explanation" class="panel explanation-panel">
        <h2>PMC 结果解释</h2>
        <p>{{ formattedExplanation }}</p>
        <small>解释来源：{{ result.explanation.source === 'llm' ? 'DeepSeek' : '确定性模板' }}</small>
      </section>

      <section v-if="hasReport" class="decision-summary-grid">
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
          <ul v-if="presentedRecommendedActions.length">
            <li v-for="action in presentedRecommendedActions" :key="`${action.priority}-${action.material}-${action.action}`">
              {{ action.action }}
            </li>
          </ul>
          <p v-else>当前报告未返回建议动作。</p>
        </article>
      </section>

      <section v-if="hasReport" class="panel key-material-panel">
        <h2>关键物料 Top 5</h2>
        <p>依据既有生产影响顺序，展示当前最需要优先处理的 5 项物料。</p>
        <div class="table-wrap">
          <table class="presentation-table">
            <thead><tr><th>关键物料</th><th>缺口数量</th><th>风险信息</th></tr></thead>
            <tbody>
              <tr v-for="(item, index) in presentedBlockingMaterials" :key="item.material">
                <td>
                  <div class="material-presentation">
                    <strong>{{ materialPresentation(item, index).label }}</strong>
                    <small v-if="materialPresentation(item, index).code">编码 {{ materialPresentation(item, index).code }}</small>
                  </div>
                </td>
                <td><strong>{{ item.shortage }}</strong></td>
                <td>{{ presentationRiskLabel(item) }}</td>
              </tr>
              <tr v-if="!hasBlockingMaterials"><td colspan="3" class="empty">暂无阻塞物料可展示。</td></tr>
            </tbody>
          </table>
        </div>
        <p v-if="remainingBlockingMaterialCount" class="material-overflow-hint">
          其余 {{ remainingBlockingMaterialCount }} 项已纳入完整分析，本页仅展示最高优先级物料。
        </p>
      </section>

      <section v-if="hasReport && hasRecommendedActions" class="panel">
        <h2>建议行动</h2>
        <ul class="action-list">
          <li v-for="action in presentedRecommendedActions" :key="`${action.priority}-${action.material}-${action.action}`">
            {{ actionMaterialLabel(action) }}：{{ action.action }}
          </li>
        </ul>
      </section>

      <section v-else-if="hasReport" class="panel empty-result-panel">
        <h2>暂无建议动作</h2>
        <p>当前报告未返回建议动作，请重新分析或稍后重试。</p>
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
          <small>{{ formatScenarioImprovement(result.scenario) }}</small>
        </article>
      </section>

      <section v-if="visibleFollowUpQuestions.length" class="panel follow-up-panel">
        <h2>Agent 主动追问</h2>
        <p>以下信息缺失，系统不会自行编造采购参数。</p>
        <ul class="action-list"><li v-for="question in visibleFollowUpQuestions" :key="question">{{ question }}</li></ul>
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
