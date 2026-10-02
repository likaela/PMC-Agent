<script setup lang="ts">
import { useRouter } from "vue-router";
import { computed } from "vue";
import Icon from "../components/Icon.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { useAgent } from "../composables/useAgent";
import { demoScenarios } from "../data/demoScenarios";
const { mode } = useAgent();
const router = useRouter();
const offlineCards = [
  {
    id: "production",
    index: "01",
    icon: "layers",
    title: "生产物料分析",
    description: "从生产目标出发，查看物料需求、已知库存与缺口。",
    prompt: "生产 1,000 台 ABC-1000，物料够吗？",
    tag: "项目资料示例",
  },
  {
    id: "inventory",
    index: "02",
    icon: "database",
    title: "库存事实查询",
    description: "快速查看库存数值，同时核对数据来源与适用条件。",
    prompt: "查询主板库存",
    tag: "项目资料示例",
  },
  {
    id: "purchase",
    index: "03",
    icon: "cart",
    title: "采购建议样例",
    description: "阅读采购建议与依据，明确数量之外的使用边界。",
    prompt: "查看独立采购建议样例",
    tag: "独立采购样例",
  },
];
const cards = computed(() =>
  mode.value === "mock"
    ? offlineCards
    : demoScenarios.map((s, index) => ({
        ...s,
        index: `0${index + 1}`,
        tag: "后端独立合成 Demo",
      })),
);
function openScenario(id: string) {
  router.push({ path: "/workspace", query: { scenario: id } });
}
</script>
<template>
  <div class="home-page">
    <section class="hero card">
      <div class="hero-content">
        <div class="eyebrow">
          <span class="tiny-line"></span>从问题到计划，让依据更清楚
        </div>
        <h1>复杂的物料问题，<br />从这里<span>理清思路。</span></h1>
        <p>
          你的制造业智能计划助手。提出问题，读懂分析结论，<br
            class="desktop-only"
          />在同一个工作台查看物料明细与数据来源。
        </p>
        <RouterLink class="primary-button hero-button" to="/workspace"
          >开始分析<Icon name="arrow" :size="19"
        /></RouterLink>
        <div class="hero-foot">
          <Icon name="checkcircle" :size="15" />结论与来源一起呈现<span
          ></span>保留每一次分析上下文
        </div>
      </div>
      <div class="hero-visual" aria-hidden="true">
        <div class="visual-grid"></div>
        <div class="visual-orbit orbit-one"></div>
        <div class="visual-orbit orbit-two"></div>
        <div class="floating-tag tag-top">
          <span class="tag-icon"><Icon name="layers" :size="19" /></span>
          <div>
            <small>示例生产目标</small
            ><strong
              >{{ mode === "mock" ? "ABC-1000" : "DEMO-PMC-01" }}
              <em>{{
                mode === "mock" ? "× 1,000 台" : "× 50 / 100 台"
              }}</em></strong
            >
          </div>
        </div>
        <div class="visual-cube"><Icon name="cube" :size="84" /></div>
        <div class="floating-tag tag-bottom">
          <span class="tag-icon orange"><Icon name="alert" :size="19" /></span>
          <div>
            <small>{{
              mode === "mock"
                ? "项目资料示例 · 已知缺口"
                : "独立合成场景 · 后端分析"
            }}</small
            ><strong
              >{{ mode === "mock" ? "主板" : "查询后展示" }}
              <em>{{ mode === "mock" ? "200 件" : "结果与来源" }}</em></strong
            >
          </div>
          <span class="mini-line"></span>
        </div>
        <span class="visual-caption">连接问题、结论与依据</span>
      </div>
    </section>
    <div class="section-heading">
      <div>
        <h2>从一个具体问题开始</h2>
        <p>选择场景，体验完整的查询与分析流程</p>
      </div>
      <span class="subtle-label">{{
        mode === "mock" ? "离线固定样例" : "在线独立 Demo · 结果由后端生成"
      }}</span>
    </div>
    <section class="scenario-cards" aria-label="演示场景">
      <article v-for="card in cards" :key="card.id" class="scenario-card card">
        <div class="scenario-card-top">
          <span class="scene-icon"><Icon :name="card.icon" :size="24" /></span
          ><span class="scene-index">{{ card.index }}</span>
        </div>
        <h3>{{ card.title }}</h3>
        <p>{{ card.description }}</p>
        <span class="scenario-label">{{ card.tag }}</span
        ><button class="scenario-question" @click="openScenario(card.id)">
          <span>{{ card.prompt }}</span
          ><Icon name="arrow" :size="18" />
        </button>
      </article>
    </section>
    <section class="home-bottom">
      <div class="card workflow-card">
        <div class="card-heading">
          <h2>一条清晰的分析路径</h2>
          <Icon name="sparkles" :size="19" />
        </div>
        <div class="workflow">
          <div>
            <span>1</span><strong>描述目标</strong>
            <p>产品、数量与适用条件</p>
          </div>
          <Icon name="chevron" :size="16" />
          <div>
            <span>2</span><strong>阅读结论</strong>
            <p>先看结论，再看缺口</p>
          </div>
          <Icon name="chevron" :size="16" />
          <div>
            <span>3</span><strong>核对依据</strong>
            <p>来源、时效与边界</p>
          </div>
        </div>
      </div>
      <div class="card boundary-card">
        <div class="card-heading">
          <h2>当前能力边界</h2>
          <StatusBadge tone="blue">{{
            mode === "mock" ? "离线样例" : "事实查询"
          }}</StatusBadge>
        </div>
        <p>
          在线查询支持库存、批次、已发布 BOM、多层 BOM 生产能力与采购建议。
          信息不足时请求补充或明确拒答，不估算未知库存；不执行排产或采购下单。
        </p>
        <div class="boundary-note">
          <Icon name="shield" :size="16" />演示结果不构成真实生产或采购决策
        </div>
      </div>
    </section>
  </div>
</template>
