<script setup>
defineProps({
  steps: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
})

function stageLabel(step) {
  return ({
    '用户请求': '任务理解',
    '任务解析': '任务理解',
    '任务校验': '任务理解',
    'BOM 分析': '物料分析',
    'MRP 齐套分析': '库存检查',
    '采购分析': '采购分析',
    '生产决策': '生产决策',
    '报告生成': '结果生成',
    '等待业务补充': '补充采购信息',
    '会话上下文复用': '会话复用',
    '结果解释': '结果说明',
    '方案数量解析': '方案调整',
    '方案生成': '方案比较',
  }[step] || '分析处理')
}

function statusLabel(status) {
  return ({
    completed: '已完成',
    waiting: '等待补充信息',
    error: '执行异常',
    running: '正在执行',
  }[status] || '状态待确认')
}
</script>

<template>
  <section class="workflow-trace" aria-live="polite">
    <div class="workflow-trace-heading">
      <div>
        <h2>Agent 分析进度</h2>
        <p>展示制造分析阶段与完成状态，不展示模型内部推理。</p>
      </div>
      <span v-if="loading" class="trace-loading">正在分析</span>
    </div>

    <p v-if="loading" class="trace-pending">生产任务已提交，正在依次完成物料、库存、采购与生产决策分析。</p>
    <p v-else-if="!steps.length" class="trace-empty">完成一次生产分析后，这里将展示各阶段进度。</p>
    <ol v-else class="execution-trace">
      <li v-for="step in steps" :key="`${step.step}-${step.status}`" :data-status="step.status">
        <strong>{{ stageLabel(step.step) }}</strong>
        <code>{{ statusLabel(step.status) }}</code>
        <span>{{ step.summary }}</span>
      </li>
    </ol>
  </section>
</template>
