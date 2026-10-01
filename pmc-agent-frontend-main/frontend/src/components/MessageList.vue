<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { useAgent } from "../composables/useAgent";
import Icon from "./Icon.vue";
const { messages, selectedId, pending, select, mode } = useAgent();
const list = ref<HTMLElement>();
watch(
  () => [messages.value.length, pending.value],
  async () => {
    await nextTick();
    list.value?.scrollTo({ top: list.value.scrollHeight, behavior: "instant" });
  },
);
</script>
<template>
  <div ref="list" class="message-list" aria-label="对话记录">
    <div class="welcome-message">
      <span class="assistant-avatar"><Icon name="sparkles" :size="18" /></span>
      <div>
        <strong>你好，我是 PMC-Agent</strong>
        <p>
          告诉我你想分析的生产目标或物料问题，我会把结论和依据整理在分析结论区。
        </p>
        <span class="welcome-label">{{
          mode === "mock" ? "当前使用固定演示场景" : "真实接口等待接入"
        }}</span>
      </div>
    </div>
    <div v-for="message in messages" :key="message.id" class="message-pair">
      <div class="user-message">
        <div>{{ message.question }}</div>
        <span>你 · {{ message.requestedAt }}</span>
      </div>
      <button
        class="assistant-message"
        :class="{ 'is-selected': selectedId === message.id }"
        :disabled="pending"
        :aria-pressed="selectedId === message.id"
        @click="select(message.id)"
      >
        <span class="assistant-avatar"
          ><Icon name="sparkles" :size="16"
        /></span>
        <div>
          <div class="message-meta">
            <strong>PMC-Agent</strong
            ><span>{{
              selectedId === message.id ? "当前结果" : "查看结果"
            }}</span>
          </div>
          <p v-if="message.state === 'pending'" class="loading-label">
            正在等待分析结果<span class="loading-dots">···</span>
          </p>
          <p v-else-if="message.state === 'cancelled'">
            请求已取消，未生成分析结论。
          </p>
          <p v-else-if="message.error">{{ message.error.message }}</p>
          <p v-else>{{ message.result?.answer }}</p>
          <small v-if="message.result"
            ><Icon name="link" :size="12" />{{
              message.result.sources[0]?.kind
            }}
            · 来源可查</small
          >
        </div>
      </button>
    </div>
  </div>
</template>
