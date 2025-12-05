<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { DocumentRecord } from '$lib/types';

  export let docs: DocumentRecord[] = [];
  export let loading = false;
  export let error = '';

  const dispatch = createEventDispatcher<{ select: { id: string } }>();

  function formatDate(value?: string) {
    if (!value) return '';
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
      <p class="eyebrow">04</p>
      <h2>文档列表</h2>
      <p class="muted">点击行快速填充文档 ID。</p>
    </div>
    <slot name="actions" />
  </div>
  {#if error}
    <p class="error">{error}</p>
  {/if}
  {#if loading}
    <p class="muted">加载中…</p>
  {:else if docs.length === 0}
    <p class="muted">暂无文档，先上传一个吧。</p>
  {:else}
    <div class="doc-list">
      {#each docs as doc}
        <button class="doc-row" on:click={() => dispatch('select', { id: doc.id })}>
          <div class="doc-main">
            <p class="strong">{doc.original_filename}</p>
            <p class="muted small">{doc.id}</p>
          </div>
          <div class="doc-meta">
            <p class="muted small">{formatDate(doc.created_at)}</p>
            {#if doc.tags?.length}
              <div class="chips inline">
                {#each doc.tags as tag}
                  <span class="chip ghost">{tag}</span>
                {/each}
              </div>
            {/if}
          </div>
        </button>
      {/each}
    </div>
  {/if}
</section>
