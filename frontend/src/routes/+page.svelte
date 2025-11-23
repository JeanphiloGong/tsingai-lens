<script lang="ts">
  import { onMount } from 'svelte';
  import DocList from '$lib/components/DocList.svelte';
  import DetailPanel from '$lib/components/DetailPanel.svelte';
  import HeroHeader from '$lib/components/HeroHeader.svelte';
  import QueryPanel from '$lib/components/QueryPanel.svelte';
  import UploadPanel from '$lib/components/UploadPanel.svelte';
  import {
    apiBase,
    fetchDocumentDetail,
    fetchDocumentGraph,
    fetchDocumentKeywords,
    healthCheck,
    listDocuments,
    runQuery,
    uploadDocument
  } from '$lib/api';
  import type {
    DocumentDetailResponse,
    DocumentRecord,
    GraphPayload,
    SourceEntry,
    UploadResponse
  } from '$lib/types';
  import '../app.css';

  let health = 'checking';
  let docs: DocumentRecord[] = [];
  let listLoading = false;
  let listError = '';

  let selectedDocId = '';
  let detail: DocumentDetailResponse | null = null;
  let detailLoading = false;
  let detailError = '';

  let uploadResult: UploadResponse | null = null;
  let uploadError = '';
  let uploading = false;

  let question = '';
  let topK = 4;
  let answer = '';
  let sources: SourceEntry[] = [];
  let queryError = '';
  let querying = false;

  onMount(async () => {
    try {
      const res = await healthCheck();
      health = res.status;
    } catch (err) {
      console.error(err);
      health = 'unavailable';
    }
    await refreshDocs();
  });

  async function refreshDocs() {
    listLoading = true;
    listError = '';
    try {
      const res = await listDocuments();
      docs = res.items ?? [];
    } catch (err) {
      listError = err instanceof Error ? err.message : '获取文档列表失败';
    } finally {
      listLoading = false;
    }
  }

  async function handleUpload(event: CustomEvent<{ file: File; tags: string; metadata: string }>) {
    const { file, tags, metadata } = event.detail;
    uploading = true;
    uploadError = '';
    try {
      uploadResult = await uploadDocument({ file, tags, metadata });
      selectedDocId = uploadResult.id;
      await refreshDocs();
      await loadDetail(uploadResult.id);
    } catch (err) {
      uploadError = err instanceof Error ? err.message : '上传失败';
    } finally {
      uploading = false;
    }
  }

  async function handleQuery(event: CustomEvent<{ question: string; topK: number }>) {
    const { question: q, topK: k } = event.detail;
    if (!q.trim()) {
      queryError = '请输入问题';
      return;
    }
    querying = true;
    queryError = '';
    try {
      const res = await runQuery(q.trim(), k);
      answer = res.answer;
      sources = res.sources ?? [];
    } catch (err) {
      queryError = err instanceof Error ? err.message : '检索失败';
    } finally {
      querying = false;
    }
  }

  async function loadDetail(id?: string) {
    const targetId = (id ?? selectedDocId).trim();
    if (!targetId) return;
    selectedDocId = targetId;
    detailLoading = true;
    detailError = '';
    try {
      const [recordDetail, kwRes, graphRes] = await Promise.all([
        fetchDocumentDetail(targetId),
        fetchDocumentKeywords(targetId).catch(() => null),
        fetchDocumentGraph(targetId).catch(() => null)
      ]);

      detail = {
        record: recordDetail.record,
        meta: {
          ...recordDetail.meta,
          keywords: kwRes?.keywords ?? recordDetail.meta.keywords,
          graph: (graphRes?.graph as GraphPayload | undefined) ?? recordDetail.meta.graph,
          mindmap: (graphRes?.mindmap as Record<string, unknown> | undefined) ?? recordDetail.meta.mindmap
        }
      };
    } catch (err) {
      detailError = err instanceof Error ? err.message : '加载文档详情失败';
      detail = null;
    } finally {
      detailLoading = false;
    }
  }
</script>

<svelte:head>
  <title>TsingAI-Lens · SvelteKit 前端</title>
</svelte:head>

<div class="page">
  <HeroHeader
    health={health}
    apiBase={apiBase}
    docCount={docs.length}
    selectedDocId={selectedDocId}
    on:refresh={refreshDocs}
  />

  <main class="layout">
    <UploadPanel uploading={uploading} error={uploadError} result={uploadResult} on:upload={handleUpload} />

    <QueryPanel
      bind:question
      bind:topK
      answer={answer}
      sources={sources}
      querying={querying}
      error={queryError}
      on:query={handleQuery}
    />

    <DetailPanel
      bind:docId={selectedDocId}
      detail={detail}
      loading={detailLoading}
      error={detailError}
      on:load={(e) => loadDetail(e.detail.id)}
    />

    <DocList docs={docs} loading={listLoading} error={listError} on:select={(e) => loadDetail(e.detail.id)}>
      <button
        slot="actions"
        class="secondary ghost"
        on:click={refreshDocs}
        disabled={listLoading}
        aria-label="刷新列表"
      >
        {listLoading ? '刷新中…' : '刷新'}
      </button>
    </DocList>
  </main>
</div>
