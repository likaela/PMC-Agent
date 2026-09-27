<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { analyzePmc, ApiError, resumePurchaseParameters } from './api/pmc'

const analysisForm = reactive({ product: 'KQ-Z112', bom_version: 'V01', quantity: 1 })
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const workflow = ref(null)
const parameterForms = reactive({})
const isAnalyzing = ref(false)
const isResuming = ref(false)
const errorMessage = ref('')
const lastAction = ref('')

const statusLabel = computed(() => ({
  ready: '可开工',
  blocked: '生产受阻',
  procurement_pending: '采购待到货',
  data_incomplete: '数据不完整',
}[workflow.value?.decision_status] || '等待分析'))

const reportJson = computed(() => workflow.value?.report ? JSON.stringify(workflow.value.report, null, 2) : '')

function resetParameterForms(missingItems) {
  Object.keys(parameterForms).forEach((key) => delete parameterForms[key])
  missingItems.forEach((item) => {
    parameterForms[item.material] = { supplier_code: '', safety_stock: '', lead_time_days: '' }
  })
}

function applyWorkflow(nextWorkflow) {
  workflow.value = nextWorkflow
  resetParameterForms(nextWorkflow.missing_purchase_parameters || [])
  if (nextWorkflow.errors?.length) {
    errorMessage.value = nextWorkflow.errors.join('；')
  }
}

async function submitAnalysis() {
  errorMessage.value = ''
  lastAction.value = ''
  isAnalyzing.value = true
  try {
    applyWorkflow(await analyzePmc({ ...analysisForm, quantity: Number(analysisForm.quantity) }))
    lastAction.value = '已获取后端确定性 PMC 分析结果。'
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '无法连接 PMC API。'
  } finally {
    isAnalyzing.value = false
  }
}

function buildUpdates() {
  return Object.fromEntries(
    Object.entries(parameterForms)
      .map(([material, values]) => {
        const update = {}
        if (values.supplier_code.trim()) update.supplier_code = values.supplier_code.trim()
        if (values.safety_stock !== '') update.safety_stock = Number(values.safety_stock)
        if (values.lead_time_days !== '') update.lead_time_days = Number(values.lead_time_days)
        return [material, update]
      })
      .filter(([, values]) => Object.keys(values).length > 0),
  )
}

async function submitPurchaseParameters() {
  errorMessage.value = ''
  const updates = buildUpdates()
  if (!Object.keys(updates).length) {
    errorMessage.value = '请至少填写一个物料的一项采购参数。'
    return
  }
  isResuming.value = true
  try {
    applyWorkflow(await resumePurchaseParameters(workflow.value.workflow_id, updates))
    lastAction.value = '采购参数已提交，工作流已从采购分析节点恢复。'
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '恢复 PMC 工作流失败。'
  } finally {
    isResuming.value = false
  }
}

watch(() => workflow.value?.missing_purchase_parameters, (items) => {
  if (items) resetParameterForms(items)
})
</script>

<template>
  <main class="page-shell">
    <header class="page-header">
      <div>
        <p class="eyebrow">PMC-AGENT / V1.0 BETA</p>
        <h1>生产决策 Dashboard</h1>
        <p class="subtitle">展示后端确定性工作流结果；页面不执行 BOM、MRP、风险或生产决策计算。</p>
      </div>
      <span class="api-badge">API: {{ apiBaseUrl }}</span>
    </header>

    <section class="panel analysis-panel">
      <h2>PMC 分析</h2>
      <form class="analysis-form" @submit.prevent="submitAnalysis">
        <label>产品<input v-model.trim="analysisForm.product" required /></label>
        <label>BOM 版本<input v-model.trim="analysisForm.bom_version" required /></label>
        <label>生产数量<input v-model.number="analysisForm.quantity" type="number" min="1" required /></label>
        <button :disabled="isAnalyzing" type="submit" @click.prevent="submitAnalysis">{{ isAnalyzing ? '正在分析…' : '开始分析' }}</button>
      </form>
    </section>

    <p v-if="errorMessage" class="message error">{{ errorMessage }}</p>
    <p v-if="lastAction" class="message success">{{ lastAction }}</p>

    <template v-if="workflow">
      <section class="status-grid">
        <article class="status-card" :data-status="workflow.decision_status || 'unknown'">
          <span>生产决策</span><strong>{{ statusLabel }}</strong><small>{{ workflow.decision_status || '未返回' }}</small>
        </article>
        <article class="status-card"><span>工作流状态</span><strong>{{ workflow.workflow_status }}</strong><small>workflow_id: {{ workflow.workflow_id }}</small></article>
        <article class="status-card"><span>是否可开工</span><strong>{{ workflow.can_start_production === true ? '是' : workflow.can_start_production === false ? '否' : '待确认' }}</strong><small>来自 Production Decision</small></article>
        <article class="status-card"><span>待补采购参数</span><strong>{{ workflow.missing_purchase_parameters.length }}</strong><small>来自 API 返回清单</small></article>
        <article class="status-card"><span>物料齐套率</span><strong>{{ workflow.report.known_inventory_kit_analysis?.material_readiness_rate ?? '—' }}</strong><small>来自确定性报告</small></article>
        <article class="status-card"><span>数量满足率</span><strong>{{ workflow.report.known_inventory_kit_analysis?.quantity_fulfillment_rate ?? '—' }}</strong><small>来自确定性报告</small></article>
      </section>

      <section v-if="workflow.errors.length" class="message error">
        <strong>工作流未完成：</strong>{{ workflow.errors.join('；') }}
      </section>

      <section class="panel">
        <h2>阻塞物料</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>优先级</th><th>物料</th><th>需求</th><th>可用</th><th>缺料</th><th>缺料比例</th><th>采购状态</th><th>风险</th></tr></thead>
            <tbody>
              <tr v-for="item in workflow.blocking_materials" :key="item.material">
                <td>P{{ item.priority }}</td><td>{{ item.material }}</td><td>{{ item.required }}</td><td>{{ item.available ?? '—' }}</td><td>{{ item.shortage }}</td><td>{{ item.shortage_ratio }}</td><td>{{ item.purchase_status }}</td><td>{{ item.risk_level || '待补参数' }}</td>
              </tr>
              <tr v-if="!workflow.blocking_materials.length"><td colspan="8" class="empty">API 未返回阻塞物料。</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-if="workflow.report.production_decision?.recommended_actions?.length" class="panel">
        <h2>建议行动</h2>
        <ul class="action-list">
          <li v-for="action in workflow.report.production_decision.recommended_actions" :key="`${action.priority}-${action.material}-${action.action}`">
            P{{ action.priority }} {{ action.material || '全部相关物料' }}：{{ action.action }}
          </li>
        </ul>
      </section>

      <section v-if="workflow.missing_purchase_parameters.length" class="panel">
        <div class="section-heading"><div><h2>补充采购参数</h2><p>仅提交业务人员明确提供的字段；缺失字段不会被前端猜测。</p></div><button :disabled="isResuming" @click="submitPurchaseParameters">{{ isResuming ? '正在恢复…' : '提交并恢复工作流' }}</button></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>物料</th><th>当前缺料</th><th>仍需字段</th><th>供应商编码</th><th>安全库存</th><th>提前期（天）</th></tr></thead>
            <tbody>
              <tr v-for="item in workflow.missing_purchase_parameters" :key="item.material">
                <td>{{ item.material }}</td><td>{{ item.shortage }}</td><td>{{ item.missing_fields.join(', ') }}</td>
                <td><input v-model="parameterForms[item.material].supplier_code" placeholder="SUP001" /></td>
                <td><input v-model="parameterForms[item.material].safety_stock" type="number" min="0" placeholder="0" /></td>
                <td><input v-model="parameterForms[item.material].lead_time_days" type="number" min="0" placeholder="8" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel report-panel">
        <h2>确定性 PMC 报告</h2>
        <p>以下内容为 API 返回的报告原文，前端不修改其数值或结论。</p>
        <pre>{{ reportJson }}</pre>
      </section>
    </template>
  </main>
</template>
