<script setup>
import { computed } from 'vue'

const props = defineProps({
  active: { type: Boolean, default: false },
  completedStep: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  steps: { type: Array, default: () => [] },
})

defineEmits(['start', 'continue'])

const nextStep = computed(() => props.steps[props.completedStep] || null)

function stepState(index) {
  if (index < props.completedStep) return 'completed'
  if (index === props.completedStep && props.active) return 'current'
  return 'pending'
}
</script>

<template>
  <section class="demo-guide" aria-label="三分钟完整演示引导">
    <div>
      <span class="demo-guide-kicker">三分钟演示路径</span>
      <h2>从自然语言需求到生产决策</h2>
      <p>每一步都基于实际分析结果继续推进，系统不会预设或伪造生产结论。</p>
    </div>
    <ol>
      <li v-for="(step, index) in steps" :key="step.label" :data-state="stepState(index)">
        <b>{{ index + 1 }}</b>
        <span>{{ step.label }}</span>
      </li>
    </ol>
    <button v-if="!active" type="button" :disabled="loading" @click="$emit('start')">开始完整演示</button>
    <button v-else-if="nextStep" type="button" :disabled="loading" @click="$emit('continue')">
      {{ loading ? '正在分析…' : `继续：${nextStep.label}` }}
    </button>
    <p v-else class="demo-complete">完整演示已完成，你也可以继续自由提问。</p>
  </section>
</template>
