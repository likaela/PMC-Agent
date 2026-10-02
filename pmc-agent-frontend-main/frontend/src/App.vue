<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute } from "vue-router";
import Icon from "./components/Icon.vue";
import { useAgent } from "./composables/useAgent";
import type { DataMode, ScenarioId } from "./data/model";
const route = useRoute();
const { mode, scenario, pending, setMode, setScenario } = useAgent();
const menuOpen = ref(false);
const help = ref<HTMLDialogElement>();
function focusMain() {
  document.getElementById("main-content")?.focus();
}
watch(
  () => route.path,
  () => {
    menuOpen.value = false;
  },
);
</script>
<template>
  <a class="skip-link" href="#main-content" @click.prevent="focusMain"
    >跳转到主要内容</a
  >
  <div class="app-layout" @keydown.esc="menuOpen = false">
    <header class="mobile-header">
      <RouterLink to="/" class="brand"
        ><span class="brand-symbol"><Icon name="cube" :size="25" /></span
        ><strong>PMC-Agent</strong></RouterLink
      >
      <button
        class="icon-button"
        :aria-expanded="menuOpen"
        aria-controls="sidebar"
        :aria-label="menuOpen ? '关闭导航' : '打开导航'"
        @click="menuOpen = !menuOpen"
      >
        <Icon :name="menuOpen ? 'close' : 'menu'" />
      </button>
    </header>
    <button
      v-if="menuOpen"
      class="nav-backdrop"
      aria-label="关闭导航遮罩"
      @click="menuOpen = false"
    ></button>
    <aside id="sidebar" class="sidebar" :class="{ 'is-open': menuOpen }">
      <RouterLink to="/" class="brand desktop-brand"
        ><span class="brand-symbol"><Icon name="cube" :size="28" /></span
        ><span
          ><strong>PMC-Agent</strong><small>制造业智能计划助手</small></span
        ></RouterLink
      >
      <div class="nav-label">工作空间 <span>WORKSPACE</span></div>
      <nav aria-label="主导航">
        <RouterLink to="/" class="nav-item" exact-active-class="is-active"
          ><Icon name="home" /><span>首页</span></RouterLink
        >
        <RouterLink to="/workspace" class="nav-item" active-class="is-active"
          ><Icon name="sparkles" /><span>分析工作台</span></RouterLink
        >
      </nav>
      <div class="sidebar-bottom">
        <div class="sidebar-note">
          <span class="small-icon"><Icon name="shield" :size="18" /></span
          ><strong>每个结论，有据可循</strong>
          <p>查看物料明细与来源，<br />让计划更清晰。</p>
        </div>
        <button
          class="nav-item help-button"
          @click="
            help?.showModal();
            menuOpen = false;
          "
        >
          <Icon name="help" /><span>使用说明</span
          ><Icon name="chevron" :size="16" />
        </button>
        <div class="sidebar-footer">
          <span class="status-dot"></span>Agent 客户端 <span>v1.14.1</span>
        </div>
      </div>
    </aside>
    <div class="main-shell">
      <div class="topbar">
        <div class="breadcrumb">
          工作空间 <Icon name="chevron" :size="14" /><span>{{
            route.path === "/" ? "首页" : "分析工作台"
          }}</span>
        </div>
        <div class="mode-switch">
          <span class="mode-dot" :class="{ live: mode === 'live' }"></span
          ><label for="data-mode">数据模式</label
          ><select
            id="data-mode"
            :value="mode"
            @change="
              setMode(($event.target as HTMLSelectElement).value as DataMode)
            "
          >
            <option value="mock">离线样例</option>
            <option value="live">在线 Agent</option>
          </select>
          <label v-if="mode === 'live'" for="data-space">数据空间</label>
          <select
            v-if="mode === 'live'"
            id="data-space"
            :value="scenario ?? ''"
            :disabled="pending"
            @change="
              setScenario(
                (($event.target as HTMLSelectElement).value || undefined) as
                  ScenarioId | undefined,
              )
            "
          >
            <option value="">企业事实</option>
            <option value="demo_scenario_50_vs_100">合成 Demo</option>
          </select>
        </div>
      </div>
      <main id="main-content" tabindex="-1">
        <div
          class="mode-banner"
          :class="{ 'mode-banner--live': mode === 'live' }"
        >
          <Icon :name="mode === 'mock' ? 'info' : 'link'" :size="16" /><span>{{
            mode === "mock"
              ? "演示数据 · 未连接真实后端"
              : scenario
                ? "在线 Agent · 独立合成 Demo"
                : "在线 Agent · 企业已发布事实"
          }}</span
          ><small>{{
            mode === "mock"
              ? "固定场景，仅用于功能演示"
              : "后端查询与计算 · 未知不补零"
          }}</small>
        </div>
        <RouterView />
      </main>
      <footer class="page-footer">
        <span>PMC-Agent</span><span>清晰的计划，始于可信的数据。</span>
      </footer>
    </div>
    <dialog
      ref="help"
      class="help-dialog"
      aria-labelledby="help-title"
      @click="
        (event) => {
          if (event.target === help) help?.close();
        }
      "
    >
      <div class="card-heading">
        <div>
          <span class="eyebrow">QUICK GUIDE</span>
          <h2 id="help-title">开始你的第一次分析</h2>
        </div>
        <button
          class="icon-button"
          aria-label="关闭使用说明"
          @click="help?.close()"
        >
          <Icon name="close" />
        </button>
      </div>
      <ol class="help-steps">
        <li>
          <strong>选择演示场景</strong>
          <p>
            在线模式可查询企业事实或进入独立合成
            Demo。离线模式保留固定库存、采购与异常交互样例。
          </p>
        </li>
        <li>
          <strong>阅读结论与物料明细</strong>
          <p>
            描述查询需求后发送；按提示补充缺失条件。点击历史回答，可查看对应结果、警告和来源。
          </p>
        </li>
        <li>
          <strong>核对来源和适用条件</strong>
          <p>
            “未提供”不等于
            0。演示数据不能用于真实生产决策，物料齐套也不代表产能或交期。
          </p>
        </li>
      </ol>
      <div class="soft-note">
        <Icon name="info" />
        <p>
          在线模式支持已发布库存、批次、BOM、生产能力与采购查询，并保存会话。
          独立 Demo 使用合成事实；库存齐套不代表设备产能、质量放行或交期承诺。
          前端不执行业务计算，切换数据空间会清理当前展示。
        </p>
      </div>
      <button class="primary-button full-width" @click="help?.close()">
        我知道了<Icon name="check" :size="18" />
      </button>
    </dialog>
  </div>
</template>
