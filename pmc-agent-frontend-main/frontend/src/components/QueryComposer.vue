<script setup lang="ts">
import { ref } from "vue";
import { useAgent } from "../composables/useAgent";
import Icon from "./Icon.vue";
const { draft, pending, send, cancel } = useAgent();
const composing = ref(false);
function onKey(event: KeyboardEvent) {
  if (
    event.key === "Enter" &&
    !event.shiftKey &&
    !event.isComposing &&
    !composing.value &&
    event.keyCode !== 229
  ) {
    event.preventDefault();
    void send();
  }
}
</script>
<template>
  <form class="composer" @submit.prevent="send()">
    <label for="query-input" class="sr-only">输入分析问题</label>
    <div class="composer-input">
      <textarea
        id="query-input"
        v-model="draft"
        :disabled="pending"
        maxlength="2000"
        rows="2"
        placeholder="请输入产品编码和生产数量，或物料编码与查询问题…"
        @keydown="onKey"
        @compositionstart="composing = true"
        @compositionend="composing = false"
      ></textarea>
      <div class="composer-actions">
        <span
          ><kbd>Enter</kbd> 发送
          <span class="desktop-only">· Shift + Enter 换行</span></span
        ><button
          v-if="pending"
          class="cancel-button"
          type="button"
          @click="cancel()"
        >
          <Icon name="stop" :size="14" />取消</button
        ><button
          v-else
          class="send-button"
          type="submit"
          :disabled="!draft.trim()"
          aria-label="发送问题"
        >
          <Icon name="send" :size="19" />
        </button>
      </div>
    </div>
    <p class="composer-hint">
      请填写产品编码；会话自动保存，必要信息不足时 Agent 会请求补充。
    </p>
  </form>
</template>
