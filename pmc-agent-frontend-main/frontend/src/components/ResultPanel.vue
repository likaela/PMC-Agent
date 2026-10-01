<script setup lang="ts">
import Icon from "./Icon.vue";
import StatusBadge from "./StatusBadge.vue";
import { useAgent } from "../composables/useAgent";
import { formatNumber, statusText } from "../data/model";
defineEmits<{ source: [] }>();
const { result, selected, pending, retry } = useAgent();
const errorTitles = {
  network: "请求失败，请重试",
  mapping: "当前结果暂无法完整展示",
  unconfigured: "接口尚未配置",
  unsupported: "请选择已提供的演示场景",
};
</script>
<template>
  <section
    id="analysis-result"
    class="card result-panel"
    aria-labelledby="result-title"
    aria-live="polite"
    :aria-busy="pending"
  >
    <div class="card-heading">
      <h2 id="result-title"><Icon name="file" :size="19" />分析结论</h2>
      <span class="subtle-label">{{
        pending ? "等待响应" : result ? "与所选回答同步" : "本次查询"
      }}</span>
    </div>
    <div v-if="pending" class="result-loading">
      <div class="loading-symbol"><Icon name="sparkles" :size="26" /></div>
      <h3>正在等待分析结果</h3>
      <p>本次请求完成后，将在这里展示结论与依据。</p>
      <div class="skeleton"></div>
      <div class="skeleton short"></div>
      <div class="skeleton"></div>
    </div>
    <div v-else-if="selected?.error" class="result-empty error-state">
      <span class="empty-icon warning"
        ><Icon
          :name="selected.error.code === 'unconfigured' ? 'link' : 'alert'"
          :size="29"
      /></span>
      <h3>{{ errorTitles[selected.error.code] }}</h3>
      <p>{{ selected.error.message }}</p>
      <span class="diagnostic">{{ selected.error.code.toUpperCase() }}</span
      ><button
        v-if="selected.error.code !== 'unsupported'"
        class="secondary-button"
        @click="retry()"
      >
        <Icon name="retry" :size="16" />重试原问题
      </button>
    </div>
    <div v-else-if="!result" class="result-empty">
      <span class="empty-icon"><Icon name="layers" :size="32" /></span>
      <h3>
        {{
          selected?.state === "cancelled"
            ? "本次分析已取消"
            : "让每个问题都有清晰的落点"
        }}
      </h3>
      <p>
        {{
          selected?.state === "cancelled"
            ? "没有生成新结论，可以重新发送原问题。"
            : "发送问题后，查看分析结论、物料缺口和可追溯的数据来源。"
        }}
      </p>
      <button
        v-if="selected?.state === 'cancelled'"
        class="secondary-button"
        @click="retry()"
      >
        <Icon name="retry" :size="16" />重试原问题
      </button>
      <div v-else class="empty-preview">
        <span><Icon name="checkcircle" :size="16" />结论摘要</span
        ><span><Icon name="layers" :size="16" />物料明细</span
        ><span><Icon name="link" :size="16" />数据来源</span>
      </div>
    </div>
    <div v-else class="result-body">
      <div class="result-kicker">
        <StatusBadge
          :tone="
            result.status === 'ready'
              ? 'green'
              : ['partial', 'zero', 'conflict', 'uncalculable'].includes(
                    result.status,
                  )
                ? 'orange'
                : 'blue'
          "
          >{{ statusText[result.status] }}</StatusBadge
        ><span>{{ result.sources[0]?.kind }}</span>
      </div>
      <h3>{{ result.title }}</h3>
      <p class="result-explanation">{{ result.answer }}</p>
      <div v-if="result.purchase" class="purchase-grid">
        <div>
          <span>缺料数量</span
          ><strong
            >{{ formatNumber(result.purchase.shortage)
            }}<small>{{ result.purchase.unit }}</small></strong
          >
        </div>
        <div>
          <span>安全库存</span
          ><strong
            >{{ formatNumber(result.purchase.safetyStock)
            }}<small>{{ result.purchase.unit }}</small></strong
          >
        </div>
        <div>
          <span>建议采购</span
          ><strong
            >{{ formatNumber(result.purchase.suggested)
            }}<small>{{ result.purchase.unit }}</small></strong
          >
        </div>
      </div>
      <p v-if="result.purchase" class="purchase-note">
        {{ result.purchase.note }}
      </p>
      <div class="next-action">
        <span class="next-action-icon"><Icon name="arrow" :size="18" /></span>
        <div>
          <strong>{{ result.conclusion }}</strong>
          <p>{{ result.nextAction }}</p>
        </div>
      </div>
      <div v-if="result.warnings.length" class="warning-list">
        <h4><Icon name="alert" :size="16" />使用前请留意</h4>
        <ul>
          <li v-for="warning in result.warnings" :key="warning">
            {{ warning }}
          </li>
        </ul>
      </div>
      <button class="source-inline" @click="$emit('source')">
        <Icon name="link" :size="15" /><span>查看本次分析来源与适用条件</span
        ><Icon name="arrow" :size="15" />
      </button>
    </div>
  </section>
</template>
