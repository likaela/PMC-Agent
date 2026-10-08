<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { useRoute, useRouter } from "vue-router";
import Icon from "../components/Icon.vue";
import SummaryCards from "../components/SummaryCards.vue";
import QueryComposer from "../components/QueryComposer.vue";
import MessageList from "../components/MessageList.vue";
import ResultPanel from "../components/ResultPanel.vue";
import MaterialTable from "../components/MaterialTable.vue";
import SourceDetails from "../components/SourceDetails.vue";
import { demoScenarios, DEMO_SCENARIO_ID } from "../data/demoScenarios";
import { useAgent } from "../composables/useAgent";
const route = useRoute();
const router = useRouter();
const {
  mode,
  scenario,
  draft,
  pending,
  result,
  notice,
  startEnterpriseAnalysis,
  send,
  restoreSession,
} = useAgent();
const sources = ref<InstanceType<typeof SourceDetails>>();
watch(
  () => route.query.scenario,
  (value) => {
    const online = demoScenarios.find((s) => s.id === value);
    if (
      online &&
      mode.value === "live" &&
      scenario.value === DEMO_SCENARIO_ID
    ) {
      draft.value = online.prompt;
      return;
    }
  },
  { immediate: true },
);
watch(scenario, () => {
  if (route.query.scenario) router.replace("/workspace");
});
function newAnalysis() {
  startEnterpriseAnalysis();
  router.replace("/workspace");
}
async function focusResult() {
  await nextTick();
  document.getElementById("analysis-result")?.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "instant"
      : "smooth",
  });
}
</script>
<template>
  <div class="workspace-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">ANALYSIS WORKSPACE</div>
        <h1>分析工作台<span class="heading-dot"></span></h1>
        <p>
          输入企业产品编码和生产数量，开始分析；也可以查询物料库存与采购信息。
        </p>
      </div>
      <button
        v-if="mode === 'live'"
        class="text-button"
        :disabled="pending"
        @click="restoreSession()"
      >
        恢复会话
      </button>
      <button class="secondary-button" :disabled="pending" @click="newAnalysis">
        <Icon name="plus" :size="17" />新建分析
      </button>
    </div>
    <SummaryCards />
    <div v-if="notice" class="inline-notice" role="status">
      <Icon name="info" :size="16" />{{ notice }}
    </div>
    <div class="analysis-grid">
      <section class="card chat-panel" aria-labelledby="chat-title">
        <div class="card-heading">
          <h2 id="chat-title"><Icon name="chat" :size="19" />智能查询</h2>
          <span class="assistant-status"><span></span>PMC-Agent</span>
        </div>
        <div v-if="mode === 'live' && scenario" class="quick-questions">
          <span>独立合成 Demo</span>
          <button
            v-for="demo in demoScenarios"
            :key="demo.id"
            :disabled="pending"
            @click="send(demo.prompt)"
          >
            {{ demo.label }}<Icon name="arrow" :size="15" />
          </button>
        </div>
        <MessageList />
        <QueryComposer /><button
          v-if="result"
          class="mobile-result-link"
          @click="focusResult"
        >
          查看本次分析结果<Icon name="down" :size="16" />
        </button>
      </section>
      <ResultPanel @source="sources?.reveal()" />
    </div>
    <MaterialTable
      :result="result ?? undefined"
      :pending="pending"
      @source="(ids) => sources?.reveal(ids)"
    /><SourceDetails ref="sources" :result="result ?? undefined" :mode="mode" />
  </div>
</template>
