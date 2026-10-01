<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import Icon from "./Icon.vue";
import StatusBadge from "./StatusBadge.vue";
import type { AgentResult } from "../data/model";
const props = defineProps<{ result?: AgentResult; mode: string }>();
const root = ref<HTMLElement>();
const open = ref(false);
const highlighted = ref<string[]>([]);
watch(
  () => props.result,
  () => {
    open.value = false;
    highlighted.value = [];
  },
);
async function reveal(ids: string[] = []) {
  open.value = true;
  highlighted.value = ids;
  await nextTick();
  root.value?.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
    block: "start",
  });
  root.value?.focus({ preventScroll: true });
}
defineExpose({ reveal });
</script>
<template>
  <section
    ref="root"
    class="card sources-card"
    tabindex="-1"
    aria-label="数据来源与适用条件"
  >
    <button
      class="source-toggle"
      :aria-expanded="open"
      aria-controls="source-details"
      @click="open = !open"
    >
      <span class="source-title"
        ><span class="source-icon"><Icon name="shield" :size="21" /></span
        ><span
          ><strong>数据来源与适用条件</strong
          ><small>{{
            result
              ? `${result.sources.length} 项分析来源 · ${mode === "mock" ? "演示数据" : "接口数据"}`
              : "结论的依据，与结论一样重要"
          }}</small></span
        ></span
      ><span class="source-toggle-label"
        >{{ open ? "收起详情" : "展开详情"
        }}<Icon name="down" :size="17" :class="{ rotated: open }"
      /></span>
    </button>
    <div v-if="open" id="source-details" class="source-details">
      <p class="source-disclaimer">
        <Icon name="info" :size="16" />{{
          mode === "mock"
            ? "演示数据 · 未连接真实后端。以下内容不属于当前企业实时事实。"
            : "真实接口模式。只有经适配确认的来源才会在此显示。"
        }}
      </p>
      <div v-if="!result?.sources.length" class="source-no-data">
        本次尚无来源可展示。
      </div>
      <article
        v-for="source in result?.sources"
        :key="source.id"
        class="source-record"
        :class="{ highlighted: highlighted.includes(source.id) }"
      >
        <div class="source-record-title">
          <Icon name="file" :size="18" /><strong>{{ source.title }}</strong
          ><StatusBadge
            :tone="source.kind === '项目资料示例' ? 'blue' : 'orange'"
            >{{ source.kind }}</StatusBadge
          >
        </div>
        <dl>
          <div>
            <dt>引用范围</dt>
            <dd>{{ source.scope }}（未提供字段级原始定位）</dd>
          </div>
          <div>
            <dt>来源文件 / 记录</dt>
            <dd>{{ source.reference }}</dd>
          </div>
          <div>
            <dt>数据版本</dt>
            <dd>{{ source.version ?? "未提供" }}</dd>
          </div>
          <div>
            <dt>来源发布时间</dt>
            <dd>{{ source.publishedAt ?? "未提供" }}</dd>
          </div>
          <div class="full-row">
            <dt>适用条件</dt>
            <dd>{{ source.conditions }}</dd>
          </div>
        </dl>
      </article>
    </div>
  </section>
</template>
