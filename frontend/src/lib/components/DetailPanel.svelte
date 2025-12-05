<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { DocumentDetailResponse } from '$lib/types';

  export let docId = '';
  export let detail: DocumentDetailResponse | null = null;
  export let loading = false;
  export let error = '';

  const dispatch = createEventDispatcher<{ load: { id: string } }>();

  function load() {
    dispatch('load', { id: docId });
  }

  function formatDate(value?: string) {
    if (!value) return '未记录';
    try {
      return new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      }).format(new Date(value));
    } catch (err) {
      console.error(err);
      return value;
    }
  }
</script>

<section class="card">
  <div class="card-header">
    <div>
      <p class="eyebrow">03</p>
      <h2>文档详情</h2>
      <p class="muted">输入文档 ID 或在右侧列表点击。</p>
    </div>
  </div>
  <div class="form compact">
    <div class="form-grid compact">
      <label class="field">
        <span>文档 ID</span>
        <input type="text" placeholder="上传后返回的 id" bind:value={docId} />
      </label>
      <div class="actions align-end">
        <button class="secondary" type="button" on:click={load}>
          {loading ? '加载中…' : '获取详情'}
        </button>
        {#if error}
          <span class="error">{error}</span>
        {/if}
      </div>
    </div>
  </div>

  {#if loading}
    <p class="muted">加载中…</p>
  {:else if detail}
    <div class="detail">
      <div class="detail-head">
        <div>
          <p class="muted">原始文件</p>
          <p class="strong">{detail.record.original_filename}</p>
          <p class="muted small">创建于 {formatDate(detail.record.created_at)}</p>
        </div>
        {#if detail.record.tags?.length}
          <div class="chips">
            {#each detail.record.tags as tag}
              <span class="chip ghost">{tag}</span>
            {/each}
          </div>
        {/if}
      </div>
      {#if detail.meta.summary}
        <div class="bubble">{detail.meta.summary}</div>
      {/if}
      {#if detail.meta.keywords?.length}
        <div class="section">
          <p class="muted">关键词</p>
          <div class="chips">
            {#each detail.meta.keywords as kw}
              <span class="chip">{kw}</span>
            {/each}
          </div>
        </div>
      {/if}
      <div class="section">
        <p class="muted">思维导图 JSON</p>
        <div class="json-block">
          <pre>{JSON.stringify(detail.meta.mindmap ?? {}, null, 2)}</pre>
        </div>
      </div>
    </div>
  {:else}
    <p class="muted">暂无数据，先选择或上传文档。</p>
  {/if}
</section>
