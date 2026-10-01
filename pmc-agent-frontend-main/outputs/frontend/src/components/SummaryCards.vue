<script setup lang="ts">
import { computed } from "vue";
import Icon from "./Icon.vue";
import StatusBadge from "./StatusBadge.vue";
import { useAgent } from "../composables/useAgent";
import { formatNumber, statusText } from "../data/model";
const { result, pending, selected, mode } = useAgent();
const stateLabel = computed(() =>
  pending.value
    ? "正在分析"
    : result.value
      ? statusText[result.value.status]
      : selected.value?.state === "error"
        ? "请求未完成"
        : selected.value?.state === "cancelled"
          ? "已取消"
          : "等待提问",
);
</script>
<template>
  <section class="summary-grid" aria-label="任务摘要">
    <article class="summary-card card">
      <div class="summary-label">当前产品<Icon name="box" :size="18" /></div>
      <strong :class="{ 'summary-empty': !result?.product }">{{
        result?.product ?? (pending ? "等待结果" : "未提供")
      }}</strong
      ><small>本次分析的产品型号</small>
    </article>
    <article class="summary-card card">
      <div class="summary-label">目标数量<Icon name="layers" :size="18" /></div>
      <strong :class="{ 'summary-empty': result?.quantity == null }"
        >{{ formatNumber(result?.quantity)
        }}<span v-if="result?.quantity != null">{{
          result.quantityUnit
        }}</span></strong
      ><small>用户指定的生产目标</small>
    </article>
    <article class="summary-card card">
      <div class="summary-label">
        分析状态<Icon name="sparkles" :size="18" />
      </div>
      <div class="summary-status">
        <StatusBadge
          :tone="
            result?.status === 'partial' || selected?.state === 'error'
              ? 'orange'
              : result?.status === 'ready'
                ? 'green'
                : 'blue'
          "
          >{{ stateLabel }}</StatusBadge
        >
      </div>
      <small>{{
        selected ? `请求时间 ${selected.requestedAt}` : "等待发起本次查询"
      }}</small>
    </article>
    <article class="summary-card card">
      <div class="summary-label">
        数据来源<Icon name="database" :size="18" />
      </div>
      <strong class="summary-mode">{{
        mode === "mock" ? "演示数据" : "真实接口"
      }}</strong
      ><small>{{
        result?.sources[0]?.kind ??
        (mode === "mock" ? "固定场景 · 未连接真实后端" : "待配置后端契约")
      }}</small>
    </article>
  </section>
</template>
