<script lang="ts">
  import { createEventDispatcher } from 'svelte';

  export let health = 'unknown';
  export let apiBase = '';
  export let docCount = 0;
  export let selectedDocId = '';

  const dispatch = createEventDispatcher<{ refresh: void }>();
</script>

<header class="hero">
  <div class="title-block">
    <p class="eyebrow">TsingAI-Lens · SvelteKit</p>
    <h1>文献上传 · 语义问答 · 图谱洞察</h1>
    <p class="lede">
      直连后端 API，完成文档上传解析、RAG 问答、关键词与思维导图浏览。保持轻量，专注科研工作流。
    </p>
    <div class="status">
      <span class={`pill ${health === 'ok' ? 'pill-good' : 'pill-bad'}`}>
        API {health === 'ok' ? '在线' : '不可达'}
      </span>
      <span class="pill ghost">base: {apiBase}</span>
      <button class="link-btn" on:click={() => dispatch('refresh')} aria-label="刷新文档列表">
        刷新列表
      </button>
    </div>
  </div>
  <div class="glow-card">
    <div>
      <p class="muted">当前文档</p>
      <p class="glow-number">{docCount || '—'}</p>
      <p class="muted">已注册文件</p>
    </div>
    <div class="divider"></div>
    <div>
      <p class="muted">选中文档</p>
      <p class="glow-number">{selectedDocId || '未选择'}</p>
      <p class="muted small">点击列表或上传后自动填充</p>
    </div>
  </div>
</header>
