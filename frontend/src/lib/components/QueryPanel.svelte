<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { SourceEntry } from '$lib/types';

  export let question = '';
  export let topK = 4;
  export let answer = '';
  export let sources: SourceEntry[] = [];
  export let querying = false;
  export let error = '';

  const dispatch = createEventDispatcher<{ query: { question: string; topK: number } }>();

  function submit() {
    dispatch('query', { question, topK });
  }

  const snippet = (text: string, max = 220) => (text?.length > max ? `${text.slice(0, max)}…` : text);
</script>

<section class="card">
  <div class="card-header">
    <div>
      <p class="eyebrow">02</p>
      <h2>RAG 问答</h2>
      <p class="muted">向量检索 + 大模型回答，top_k 默认 4。</p>
    </div>
  </div>
  <form class="form" on:submit|preventDefault={submit}>
    <label class="field">
      <span>问题</span>
      <textarea rows="4" placeholder="例如：GDP 与能源消耗的关系？" bind:value={question}></textarea>
    </label>
    <div class="form-grid compact">
      <label class="field">
        <span>Top K</span>
        <input type="number" min="1" max="8" bind:value={topK} />
      </label>
      <div class="actions align-end">
        <button class="primary" type="submit" disabled={querying}>
          {querying ? '检索中…' : '检索并回答'}
        </button>
        {#if error}
          <span class="error">{error}</span>
        {/if}
      </div>
    </div>
  </form>
  <div class="answer-block">
    <p class="muted">回答</p>
    <div class="bubble">{answer || '等待提问…'}</div>
  </div>
  <div class="sources">
    <div class="sources-head">
      <p class="muted">引用片段</p>
      <span class="pill ghost">{sources.length} 条</span>
    </div>
    {#if sources.length === 0}
      <p class="muted">暂无引用</p>
    {:else}
      {#each sources as source, idx}
        <div class="source-card">
          <div class="source-index">#{idx + 1}</div>
          <div>
            <p>{snippet(source.content)}</p>
            {#if source.metadata}
              <p class="muted small">源信息：{JSON.stringify(source.metadata)}</p>
            {/if}
          </div>
        </div>
      {/each}
    {/if}
  </div>
</section>
