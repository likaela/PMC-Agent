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
import { scenarios } from "../data/fixtures";
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
  messages,
  notice,
  reset,
  send,
  setScenario,
  restoreSession,
} = useAgent();
const scenarioId = ref("production");
const sources = ref<InstanceType<typeof SourceDetails>>();
watch(
  () => route.query.scenario,
  (value) => {
    const online = demoScenarios.find((s) => s.id === value);
    if (online && mode.value === "live") {
      setScenario(DEMO_SCENARIO_ID);
      draft.value = online.prompt;
      return;
    }
    const scenario = scenarios.find((s) => s.id === value);
    if (scenario && mode.value === "mock") {
      scenarioId.value = scenario.id;
      draft.value = scenario.prompt;
    }
  },
  { immediate: true },
);
watch(mode, () => {
  scenarioId.value = "production";
  if (route.query.scenario) router.replace("/workspace");
});
function fillScenario() {
  const scenario = scenarios.find((s) => s.id === scenarioId.value);
  if (scenario) draft.value = scenario.prompt;
}
function newAnalysis() {
  reset();
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
        <p>提出一个问题，让物料、结论与依据清晰呈现。</p>
      </div>
      <button
        v-if="mode === 'live'"
        class="text-button"
        :disabled="pending"
        @click="restoreSession()"
      >
        恢复会话
      </button>
      <button
        class="secondary-button"
        :disabled="pending || !messages.length"
        @click="newAnalysis"
      >
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
        <div v-if="mode === 'mock'" class="scenario-picker">
          <label for="scenario-select">演示场景</label>
          <div>
            <select
              id="scenario-select"
              v-model="scenarioId"
              :disabled="pending"
              @change="fillScenario"
            >
              <optgroup label="项目资料示例">
                <option
                  v-for="s in scenarios.filter((s) => s.category === 'project')"
                  :key="s.id"
                  :value="s.id"
                >
                  {{ s.label }}
                </option>
              </optgroup>
              <optgroup label="人工构造演示样例">
                <option
                  v-for="s in scenarios.filter(
                    (s) => s.category === 'synthetic',
                  )"
                  :key="s.id"
                  :value="s.id"
                >
                  {{ s.label }}
                </option>
              </optgroup></select
            ><button
              class="text-button"
              :disabled="pending"
              @click="fillScenario"
            >
              填入问题<Icon name="arrow" :size="14" />
            </button>
          </div>
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
        <div v-if="!messages.length && mode === 'mock'" class="quick-questions">
          <span>试着问问</span
          ><button
            :disabled="pending"
            @click="
              draft = scenarios[0]!.prompt;
              send();
            "
          >
            生产 1,000 台 ABC-1000，物料够吗？<Icon
              name="arrow"
              :size="15"
            /></button
          ><button
            :disabled="pending"
            @click="
              draft = scenarios[1]!.prompt;
              send();
            "
          >
            查询主板库存<Icon name="arrow" :size="15" />
          </button>
        </div>
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
      :result="result"
      :pending="pending"
      @source="(ids) => sources?.reveal(ids)"
    /><SourceDetails ref="sources" :result="result" :mode="mode" />
  </div>
</template>
