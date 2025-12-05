<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import type { UploadResponse } from '$lib/types';

  export let uploading = false;
  export let error = '';
  export let result: UploadResponse | null = null;

  let file: File | null = null;
  let tags = '';
  let metadata = '';
  let localError = '';

  const dispatch = createEventDispatcher<{ upload: { file: File; tags: string; metadata: string } }>();

  function onFileChange(event: Event) {
    const target = event.target as HTMLInputElement;
    file = target.files?.[0] ?? null;
    localError = '';
  }

  function submit() {
    localError = '';
    if (!file) {
      localError = '请选择要上传的文件';
      return;
    }

    if (metadata.trim()) {
      try {
        JSON.parse(metadata);
      } catch (err) {
        console.error(err);
        localError = '元数据需要合法 JSON，例如 {"source":"local"}';
        return;
      }
    }

    dispatch('upload', { file, tags, metadata });
  }

  const displayError = localError || error;

  const snippet = (text: string, max = 260) => (text?.length > max ? `${text.slice(0, max)}…` : text);
</script>

<section class="card span-2">
  <div class="card-header">
    <div>
      <p class="eyebrow">01</p>
      <h2>上传并解析文献</h2>
      <p class="muted">接受 PDF / DOCX / TXT / MD / CSV，自动生成关键词、图谱与摘要。</p>
    </div>
    <div class="hint">表单数据直接发送至 /documents</div>
  </div>
  <form class="form" on:submit|preventDefault={submit}>
    <label class="field">
      <span>选择文件</span>
      <input type="file" name="file" required on:change={onFileChange} />
    </label>
    <div class="form-grid">
      <label class="field">
        <span>标签（逗号分隔）</span>
        <input type="text" placeholder="机器学习, 经济学" bind:value={tags} name="tags" />
      </label>
      <label class="field">
        <span>元数据 JSON（可选）</span>
        <input
          type="text"
          placeholder="如 &#123;&quot;source&quot;:&quot;local&quot;&#125;"
          bind:value={metadata}
          name="metadata"
        />
      </label>
    </div>
    <div class="actions">
      <button class="primary" type="submit" disabled={uploading}>
        {uploading ? '上传中…' : '上传并解析'}
      </button>
      {#if displayError}
        <span class="error">{displayError}</span>
      {/if}
    </div>
  </form>

  {#if result}
    <div class="result">
      <div class="result-head">
        <div>
          <p class="muted">文档 ID</p>
          <p class="result-id">{result.id}</p>
        </div>
        {#if result.summary}
          <div class="summary">
            <p class="muted">摘要</p>
            <p>{snippet(result.summary)}</p>
          </div>
        {/if}
      </div>
      {#if result.keywords?.length}
        <div class="chips">
          {#each result.keywords as kw}
            <span class="chip">{kw}</span>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</section>
