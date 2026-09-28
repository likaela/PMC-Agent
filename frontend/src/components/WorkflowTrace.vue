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
</script>

<template>
  <section class="workflow-trace" aria-live="polite">
    <div class="workflow-trace-heading">
      <div>
        <h2>Agent 执行轨迹</h2>
        <p>仅展示后端公开的 Workflow 阶段状态，不展示提示词、模型推理或内部 State。</p>
      </div>
      <span v-if="loading" class="trace-loading">正在等待后端阶段结果</span>
    </div>

    <p v-if="loading" class="trace-pending">请求已提交，BOM、MRP、采购与生产决策仍由后端确定性工作流执行。</p>
    <p v-else-if="!steps.length" class="trace-empty">完成一次分析后，这里将展示本次 Workflow 的公开执行阶段。</p>
    <ol v-else class="execution-trace">
      <li v-for="step in steps" :key="`${step.step}-${step.status}`" :data-status="step.status">
        <strong>{{ step.step }}</strong>
        <code>{{ step.status }}</code>
        <span>{{ step.summary }}</span>
      </li>
    </ol>
  </section>
</template>
