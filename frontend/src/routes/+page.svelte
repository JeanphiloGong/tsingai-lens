<script lang="ts">
  import { onMount } from 'svelte';
  import { runQuery } from '$lib/api/chat';
  import { fetchFileStatus, uploadFile } from '$lib/api/file';
  import {
    fetchDocumentDetail,
    fetchDocumentGraph,
    fetchDocumentKeywords,
    listDocuments
  } from '$lib/api/graph';
  import type { DocumentRecord, GraphData, GraphEdge, GraphNode } from '$lib/api/types/common';
  import type { QueryResponse } from '$lib/api/types/chat';
  import type { FileStatusResponse } from '$lib/api/types/file';
  import type { DocumentDetailResponse, GraphResponse } from '$lib/api/types/graph';
  import { healthCheck } from '$lib/api/health';

  const metadataPlaceholder = '{"source":"manual"}';
  const modeOptions = ['optimize', 'precision', 'recall'] as const;
  const palette = ['#0ea5e9', '#6366f1', '#10b981', '#f59e0b', '#ec4899', '#14b8a6', '#f97316'];

  // 健康状态
  let health = 'unknown';
  let healthLoading = false;

  // 上传
  let uploading = false;
  let uploadMsg = '';
  let lastUploadId = '';
  let tags = '';
  let metadata = '';
  let file: File | null = null;

  // 列表
  let documents: DocumentRecord[] = [];
  let listLoading = false;
  let errorMsg = '';
  let searchTerm = '';
  let statusFilter: 'all' | 'pending' | 'processing' | 'completed' | 'failed' = 'all';

  // 详情
  let selectedId = '';
  let detailLoading = false;
  let detail: DocumentDetailResponse | null = null;
  let keywords: string[] = [];
  let graphSnapshot: GraphResponse | null = null;
  let detailStatus: FileStatusResponse | null = null;
  let activeDetailTab: 'summary' | 'keywords' | 'info' | 'graph' = 'summary';

  // 图谱
  let focusedNodeId = '';

  // 聊天
  let queryText = '';
  let mode: (typeof modeOptions)[number] = 'optimize';
  let topK = 5;
  let maxEdges = 80;
  let queryLoading = false;
  let queryError = '';
  let queryResult: QueryResponse | null = null;

  type LayoutNode = GraphNode & { x: number; y: number; color: string };
  type LayoutEdge = GraphEdge & { sourceNode?: LayoutNode; targetNode?: LayoutNode };
  let filteredDocuments: DocumentRecord[] = [];
  let docStats = { total: 0, completed: 0, failed: 0 };
  let activeDocs: string[] = [];
  let graphLayout: { nodes: LayoutNode[]; edges: LayoutEdge[] } = { nodes: [], edges: [] };

  $: filteredDocuments = documents.filter((doc) => {
    const matchTerm =
      !searchTerm ||
      doc.original_filename?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      doc.tags?.some((t) => t.toLowerCase().includes(searchTerm.toLowerCase()));
    const matchStatus = statusFilter === 'all' ? true : doc.status === statusFilter;
    return matchTerm && matchStatus;
  });

  $: docStats = {
    total: documents.length,
    completed: documents.filter((d) => d.status === 'completed').length,
    failed: documents.filter((d) => d.status === 'failed').length
  };

  $: activeDocs = Array.from(
    new Set((queryResult?.sources ?? []).map((s) => s.doc_id).filter(Boolean) as string[])
  );

  $: graphLayout = buildLayout(graphSnapshot?.graph ?? (detail?.meta.graph as GraphData | undefined));

  onMount(() => {
    init();
  });

  async function init() {
    healthLoading = true;
    try {
      const res = await healthCheck();
      health = res.status || 'ok';
    } catch (e) {
      health = 'down';
      errorMsg = e instanceof Error ? e.message : '健康检查失败';
    } finally {
      healthLoading = false;
    }
    await loadList();
  }

  function onFileChange(event: Event) {
    const t = event.target as HTMLInputElement;
    file = t.files?.[0] ?? null;
  }

  async function handleUpload() {
    if (!file) {
      uploadMsg = '请选择文件';
      return;
    }
    if (metadata.trim()) {
      try {
        JSON.parse(metadata);
      } catch {
        uploadMsg = '元数据需合法 JSON';
        return;
      }
    }
    uploading = true;
    uploadMsg = '上传中...';
    try {
      const res = await uploadFile({ file, tags, metadata });
      lastUploadId = res.id;
      uploadMsg = `已提交, 状态: ${res.status || 'pending'}`;
      pollStatus(res.id);
      await loadList();
      selectedId = res.id;
      await loadDetail(res.id);
    } catch (e) {
      uploadMsg = e instanceof Error ? e.message : '上传失败';
    } finally {
      uploading = false;
    }
  }

  async function pollStatus(id: string) {
    let status = 'pending';
    while (status === 'pending' || status === 'processing') {
      await new Promise((r) => setTimeout(r, 3200));
      try {
        const s = await fetchFileStatus(id);
        status = s.status;
        uploadMsg = `状态: ${s.status}${s.status_message ? ' - ' + s.status_message : ''}`;
        await patchListStatus(s);
        if (selectedId === id) detailStatus = s;
      } catch {
        uploadMsg = '状态查询失败';
        break;
      }
    }
  }

  async function loadList() {
    listLoading = true;
    errorMsg = '';
    try {
      documents = await listDocuments();
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : '列表获取失败';
    } finally {
      listLoading = false;
    }
  }

  async function selectDoc(id: string, tab: 'summary' | 'graph' = 'summary') {
    selectedId = id;
    activeDetailTab = tab;
    await loadDetail(id);
  }

  async function loadDetail(id: string) {
    detailLoading = true;
    errorMsg = '';
    focusedNodeId = '';
    try {
      const [d, k, g, status] = await Promise.all([
        fetchDocumentDetail(id),
        fetchDocumentKeywords(id),
        fetchDocumentGraph(id),
        fetchFileStatus(id)
      ]);
      detail = d;
      keywords = k;
      graphSnapshot = g;
      detailStatus = status;
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : '详情获取失败';
    } finally {
      detailLoading = false;
    }
  }

  async function refreshStatus() {
    if (!selectedId) return;
    try {
      detailStatus = await fetchFileStatus(selectedId);
      await patchListStatus(detailStatus);
    } catch (e) {
      errorMsg = e instanceof Error ? e.message : '状态刷新失败';
    }
  }

  async function patchListStatus(s: FileStatusResponse) {
    documents = documents.map((d) =>
      d.id === s.id
        ? { ...d, status: s.status, status_message: s.status_message, updated_at: s.updated_at }
        : d
    );
  }

  async function handleQuery() {
    if (!queryText.trim()) {
      queryError = '请输入问题';
      return;
    }
    queryLoading = true;
    queryError = '';
    try {
      queryResult = await runQuery({
        query: queryText.trim(),
        mode,
        top_k_cards: Number(topK) || 5,
        max_edges: Number(maxEdges) || 80
      });
      const firstDoc = queryResult.sources.find((s) => s.doc_id)?.doc_id;
      if (firstDoc) {
        await selectDoc(firstDoc, 'graph');
      }
    } catch (e) {
      queryError = e instanceof Error ? e.message : '问答失败';
    } finally {
      queryLoading = false;
    }
  }

  function colorForType(type?: string, idx = 0) {
    if (!type) return palette[idx % palette.length];
    const hash = type.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return palette[hash % palette.length];
  }

  function buildLayout(graph?: GraphData): { nodes: LayoutNode[]; edges: LayoutEdge[] } {
    if (!graph?.nodes?.length) return { nodes: [], edges: [] };
    const count = graph.nodes.length;
    const radius = 120 + Math.min(count, 18) * 6;
    const centerX = 260;
    const centerY = 180;
    const layoutNodes = graph.nodes.map((node, idx) => {
      const angle = (2 * Math.PI * idx) / count;
      return {
        ...node,
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
        color: colorForType(node.type, idx)
      };
    });
    const nodeMap = new Map(layoutNodes.map((n) => [n.id, n]));
    const layoutEdges = (graph.edges ?? [])
      .map((edge) => ({
        ...edge,
        sourceNode: nodeMap.get(edge.source),
        targetNode: nodeMap.get(edge.target)
      }))
      .filter((e) => e.sourceNode && e.targetNode);
    return { nodes: layoutNodes, edges: layoutEdges };
  }

  function statusTone(status?: string) {
    if (status === 'completed') return 'bg-emerald-100 text-emerald-700 border-emerald-200';
    if (status === 'failed') return 'bg-rose-100 text-rose-700 border-rose-200';
    if (status === 'processing' || status === 'pending')
      return 'bg-amber-100 text-amber-700 border-amber-200';
    return 'bg-slate-100 text-slate-600 border-slate-200';
  }

  function formatDate(val?: string) {
    if (!val) return '—';
    const dt = new Date(val);
    if (Number.isNaN(dt.getTime())) return val;
    return dt.toLocaleString();
  }

  function onNodeKeydown(event: KeyboardEvent, nodeId: string) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      focusedNodeId = nodeId;
    }
  }
</script>

<div class="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 text-slate-900">
  <div class="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-8">
    <!-- Hero -->
    <header class="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white/80 p-6 shadow-sm backdrop-blur">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.18em] text-teal-600">Graph Q&A · Files</p>
        <h1 class="text-2xl font-bold text-slate-900">图谱问答与文件管理</h1>
        <p class="text-sm text-slate-500">上传 / 列表 / 详情 / 图谱 / 聊天 闭环。</p>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <div
          class={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold ${
            health === 'ok' || health === 'healthy'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
              : health === 'down'
                ? 'border-rose-200 bg-rose-50 text-rose-700'
                : 'border-slate-200 bg-slate-50 text-slate-600'
          }`}
        >
          <span
            class={`h-2 w-2 rounded-full ${
              health === 'down' ? 'bg-rose-500' : 'bg-emerald-500'
            }`}
          ></span>
          {healthLoading ? '检查中…' : `服务: ${health}`}
        </div>
        <div class="flex items-center gap-3 rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm">
          <span class="font-semibold">文档 {docStats.total}</span>
          <span class="text-emerald-600">✓ {docStats.completed}</span>
          <span class="text-rose-600">✕ {docStats.failed}</span>
        </div>
      </div>
    </header>

    <div class="grid gap-4 lg:grid-cols-[360px_1fr]">
      <!-- Left: Upload + List -->
      <div class="flex flex-col gap-4">
        <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="mb-3 flex items-center justify-between">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.18em] text-teal-600">Upload</p>
              <h3 class="text-lg font-bold">上传文件</h3>
              <p class="text-xs text-slate-500">POST /file/upload · 轮询 /file/status</p>
            </div>
            <button
              class="rounded-full bg-teal-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-teal-700 disabled:opacity-60"
              type="button"
              on:click={handleUpload}
              disabled={uploading}
            >
              {uploading ? '上传中…' : '上传并入图'}
            </button>
          </div>
          <div class="space-y-3">
            <label class="flex flex-col gap-1 text-sm font-semibold text-slate-800">
              <span>选择文件</span>
              <input
                class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
                type="file"
                on:change={onFileChange}
              />
            </label>
            <label class="flex flex-col gap-1 text-sm font-semibold text-slate-800">
              <span>标签</span>
              <input
                class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
                type="text"
                bind:value={tags}
                placeholder="tag1, tag2"
              />
            </label>
            <label class="flex flex-col gap-1 text-sm font-semibold text-slate-800">
              <span>元数据</span>
              <input
                class="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
                type="text"
                bind:value={metadata}
                placeholder={metadataPlaceholder}
              />
            </label>
            <p class="text-xs text-slate-500">{uploadMsg || '支持 PDF/MD/TXT/DOCX/CSV'}</p>
            {#if lastUploadId}
              <p class="text-xs text-slate-500">最新文档 ID: <span class="font-mono">{lastUploadId}</span></p>
            {/if}
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="mb-3 flex items-center justify-between gap-2">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.18em] text-teal-600">Files</p>
              <h3 class="text-lg font-bold">文档列表</h3>
            </div>
            <button
              class="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold hover:border-teal-300 hover:text-teal-700 disabled:opacity-60"
              on:click={loadList}
              disabled={listLoading}
            >
              {listLoading ? '加载中…' : '刷新列表'}
            </button>
          </div>
          <div class="mb-3 flex flex-wrap gap-2">
            <input
              class="flex-1 min-w-[160px] rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
              type="search"
              placeholder="搜索文件名/标签"
              bind:value={searchTerm}
            />
            <select
              class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
              bind:value={statusFilter}
            >
              <option value="all">全部</option>
              <option value="completed">成功</option>
              <option value="processing">处理中</option>
              <option value="pending">待处理</option>
              <option value="failed">失败</option>
            </select>
          </div>
          {#if errorMsg}
            <p class="mb-2 text-sm font-semibold text-rose-600">{errorMsg}</p>
          {/if}
          <div class="flex max-h-[460px] flex-col gap-2 overflow-auto">
            {#if filteredDocuments.length === 0}
              <div class="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
                {listLoading ? '加载中…' : '暂无文档'}
              </div>
            {:else}
              {#each filteredDocuments as doc}
                <button
                  class={`w-full rounded-xl border px-3 py-3 text-left transition ${
                    selectedId === doc.id
                      ? 'border-teal-400 bg-teal-50 shadow-sm'
                      : 'border-slate-200 bg-slate-50 hover:border-teal-300'
                  }`}
                  on:click={() => selectDoc(doc.id)}
                >
                  <div class="flex items-start justify-between gap-3">
                    <div class="space-y-1">
                      <div class="text-sm font-bold text-slate-900">{doc.original_filename}</div>
                      <p class="text-xs text-slate-500">{doc.status_message || doc.status || 'pending'}</p>
                      {#if doc.tags?.length}
                        <div class="flex flex-wrap gap-1">
                          {#each doc.tags as tag}
                            <span class="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-700">{tag}</span>
                          {/each}
                        </div>
                      {/if}
                    </div>
                    <div class="text-right">
                      <div class={`mb-1 inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-semibold ${statusTone(doc.status)}`}>
                        <span class="h-1.5 w-1.5 rounded-full bg-current"></span>
                        {doc.status || 'pending'}
                      </div>
                      <p class="text-[11px] text-slate-500">更新 {formatDate(doc.updated_at)}</p>
                    </div>
                  </div>
                </button>
              {/each}
            {/if}
          </div>
        </section>
      </div>

      <!-- Right: Chat + Detail -->
      <div class="flex flex-col gap-4">
        <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="mb-3 flex items-center justify-between gap-2">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.18em] text-teal-600">Chat</p>
              <h3 class="text-lg font-bold">图谱问答</h3>
              <p class="text-xs text-slate-500">POST /chat/query</p>
            </div>
            <button
              class="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold hover:border-teal-300 hover:text-teal-700 disabled:opacity-60"
              type="button"
              on:click={handleQuery}
              disabled={queryLoading}
            >
              {queryLoading ? '提问中…' : '运行问答'}
            </button>
          </div>
          <div class="grid grid-cols-1 gap-3 md:grid-cols-[1fr_220px] md:items-end">
            <label class="flex flex-col gap-1 text-sm font-semibold text-slate-800">
              <span>问题</span>
              <textarea
                class="min-h-[96px] w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
                placeholder="输入要询问的内容..."
                bind:value={queryText}
              ></textarea>
            </label>
            <div class="grid grid-cols-2 gap-2">
              <label class="flex flex-col gap-1 text-xs font-semibold text-slate-800">
                <span>模式</span>
                <select
                  class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
                  bind:value={mode}
                >
                  {#each modeOptions as m}
                    <option value={m}>{m}</option>
                  {/each}
                </select>
              </label>
              <label class="flex flex-col gap-1 text-xs font-semibold text-slate-800">
                <span>top_k_cards</span>
                <input
                  class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
                  type="number"
                  min="1"
                  bind:value={topK}
                />
              </label>
              <label class="flex flex-col gap-1 text-xs font-semibold text-slate-800">
                <span>max_edges</span>
                <input
                  class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-teal-400 focus:ring-2 focus:ring-teal-100"
                  type="number"
                  min="10"
                  bind:value={maxEdges}
                />
              </label>
              <div class="flex items-end">
                <button
                  class="w-full rounded-xl bg-slate-900 px-3 py-2 text-sm font-semibold text-white shadow hover:bg-slate-800 disabled:opacity-60"
                  type="button"
                  on:click={handleQuery}
                  disabled={queryLoading}
                >
                  {queryLoading ? '提问中…' : '发送'}
                </button>
              </div>
            </div>
          </div>
          {#if queryError}
            <p class="mt-2 text-sm font-semibold text-rose-600">{queryError}</p>
          {/if}
          {#if queryResult}
            <div class="mt-4 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div class="flex items-center justify-between">
                <div class="text-sm font-semibold text-slate-900">回答</div>
                {#if activeDocs.length}
                  <div class="flex flex-wrap gap-1">
                    {#each activeDocs as docId}
                      <button
                        class="rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-100"
                        on:click={() => selectDoc(docId, 'graph')}
                      >
                        激活图谱: {docId}
                      </button>
                    {/each}
                  </div>
                {/if}
              </div>
              <div class="rounded-lg bg-slate-900 px-3 py-2 text-sm leading-relaxed text-slate-100">
                {queryResult.answer}
              </div>
              <div class="space-y-2">
                <div class="text-xs font-semibold text-slate-600">Sources</div>
                {#if queryResult.sources?.length}
                  <div class="grid gap-2 md:grid-cols-2">
                    {#each queryResult.sources as source, i}
                      <div class="rounded-lg border border-slate-200 bg-white p-2 text-xs">
                        <div class="mb-1 flex items-center justify-between">
                          <span class="flex h-6 w-6 items-center justify-center rounded-md bg-teal-600 text-[11px] font-bold text-white">{i + 1}</span>
                          <span class="font-semibold text-slate-700">{source.doc_id || '—'}</span>
                        </div>
                        <p class="text-slate-500">{source.snippet || '无摘要'}</p>
                        <div class="mt-1 flex flex-wrap gap-1 text-[11px] text-slate-500">
                          {#if source.page !== undefined}<span>page {source.page}</span>{/if}
                          {#if source.relation}<span>{source.relation}</span>{/if}
                          {#if source.score !== undefined}<span>score {source.score?.toFixed?.(3) ?? source.score}</span>{/if}
                        </div>
                      </div>
                    {/each}
                  </div>
                {:else}
                  <p class="text-xs text-slate-500">暂无引用</p>
                {/if}
              </div>
            </div>
          {/if}
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
          <div class="mb-3 flex items-center justify-between gap-3">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.18em] text-teal-600">Details</p>
              <h3 class="text-lg font-bold">文档详情</h3>
              <p class="text-xs text-slate-500">详情 / 关键词 / Info / 图谱</p>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold hover:border-teal-300 hover:text-teal-700 disabled:opacity-60"
                on:click={refreshStatus}
                disabled={!selectedId}
              >
                刷新状态
              </button>
            </div>
          </div>
          {#if !selectedId}
            <div class="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500">
              请在左侧选择文档
            </div>
          {:else if detailLoading}
            <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              加载详情中…
            </div>
          {:else if detail}
            <div class="space-y-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="space-y-1">
                  <div class="text-lg font-bold text-slate-900">{detail.record.original_filename}</div>
                  <p class="text-xs text-slate-500">ID: <span class="font-mono">{detail.record.id}</span></p>
                  <p class="text-xs text-slate-500">
                    {detailStatus ? `${detailStatus.status} ${detailStatus.status_message ?? ''}` : detail.record.status}
                  </p>
                </div>
                <div class="text-right">
                  <div class={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold ${statusTone(detailStatus?.status ?? detail.record.status)}`}>
                    <span class="h-1.5 w-1.5 rounded-full bg-current"></span>
                    {detailStatus?.status ?? detail.record.status ?? 'pending'}
                  </div>
                  <p class="text-[11px] text-slate-500">更新 {formatDate(detailStatus?.updated_at || detail.record.updated_at)}</p>
                </div>
              </div>

              <div class="flex flex-wrap gap-2 text-xs font-semibold text-slate-700">
                {#each detail.record.tags as tag}
                  <span class="rounded-full bg-slate-100 px-2 py-1">{tag}</span>
                {/each}
              </div>

              <div class="flex flex-wrap gap-2">
                {#each ['summary', 'keywords', 'info', 'graph'] as tab}
                  <button
                    class={`rounded-full border px-3 py-1 text-sm font-semibold ${
                      activeDetailTab === tab
                        ? 'border-teal-400 bg-teal-50 text-teal-700'
                        : 'border-slate-200 bg-slate-50 text-slate-700 hover:border-teal-300'
                    }`}
                    on:click={() => (activeDetailTab = tab as typeof activeDetailTab)}
                  >
                    {tab}
                  </button>
                {/each}
              </div>

              {#if activeDetailTab === 'summary'}
                <div class="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div class="text-sm font-semibold text-slate-800">摘要</div>
                  <p class="text-sm text-slate-600">{detail.meta.summary || '暂无摘要'}</p>
                </div>
              {:else if activeDetailTab === 'keywords'}
                <div class="space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div class="text-sm font-semibold text-slate-800">关键词</div>
                  {#if keywords.length}
                    <div class="flex flex-wrap gap-2">
                      {#each keywords as k}
                        <span class="rounded-full bg-slate-900 px-2 py-1 text-xs font-semibold text-slate-100">{k}</span>
                      {/each}
                    </div>
                  {:else}
                    <p class="text-sm text-slate-500">暂无关键词</p>
                  {/if}
                </div>
              {:else if activeDetailTab === 'info'}
                <div class="space-y-2 rounded-xl border border-slate-200 bg-slate-900 p-3 text-slate-100">
                  <div class="text-sm font-semibold">Info 元数据</div>
                  <pre class="max-h-64 overflow-auto text-xs leading-relaxed">{JSON.stringify(detail.meta.info ?? detail.record.metadata ?? {}, null, 2)}</pre>
                </div>
              {:else if activeDetailTab === 'graph'}
                <div class="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
                  <div class="flex flex-wrap items-center justify-between gap-2">
                    <div class="text-sm font-semibold text-slate-800">图谱/脑图</div>
                    <div class="flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      <div class="rounded-full bg-slate-200 px-2 py-1">节点 {graphLayout.nodes.length}</div>
                      <div class="rounded-full bg-slate-200 px-2 py-1">边 {graphLayout.edges.length}</div>
                    </div>
                  </div>
                  {#if graphLayout.nodes.length}
                    <div class="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-950">
                      <svg viewBox="0 0 520 360" class="h-[360px] w-full">
                        {#each graphLayout.edges as edge, i}
                          {#if edge.sourceNode && edge.targetNode}
                            <line
                              x1={edge.sourceNode.x}
                              y1={edge.sourceNode.y}
                              x2={edge.targetNode.x}
                              y2={edge.targetNode.y}
                              stroke={focusedNodeId && (edge.source === focusedNodeId || edge.target === focusedNodeId) ? '#22d3ee' : '#94a3b8'}
                              stroke-width={focusedNodeId && (edge.source === focusedNodeId || edge.target === focusedNodeId) ? 2.4 : 1.4}
                              opacity="0.7"
                            />
                            {#if edge.relation}
                              <text
                                x={(edge.sourceNode.x + edge.targetNode.x) / 2}
                                y={(edge.sourceNode.y + edge.targetNode.y) / 2 - 4}
                                class="fill-slate-400 text-[10px]"
                              >
                                {edge.relation}
                              </text>
                            {/if}
                          {/if}
                        {/each}
                        {#each graphLayout.nodes as node}
                          <g
                            role="button"
                            tabindex="0"
                            aria-label={`节点 ${node.label || node.id}`}
                            on:click={() => (focusedNodeId = node.id)}
                            on:keydown={(event) => onNodeKeydown(event, node.id)}
                            class="cursor-pointer"
                          >
                            <circle
                              cx={node.x}
                              cy={node.y}
                              r={focusedNodeId === node.id ? 20 : 14}
                              fill={node.color}
                              opacity={focusedNodeId && focusedNodeId !== node.id ? 0.5 : 0.9}
                            />
                            <text x={node.x} y={node.y + 4} text-anchor="middle" class="fill-white text-[10px] font-semibold">
                              {node.label || node.id}
                            </text>
                          </g>
                        {/each}
                      </svg>
                    </div>
                    {#if focusedNodeId}
                      <div class="text-xs text-slate-600">选中节点: {focusedNodeId}</div>
                    {/if}
                  {:else}
                    <p class="text-sm text-slate-500">暂无图数据</p>
                    <div class="rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
                      <pre class="max-h-56 overflow-auto">{JSON.stringify(graphSnapshot ?? {}, null, 2)}</pre>
                    </div>
                  {/if}
                  {#if graphSnapshot?.mindmap}
                    <div class="rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
                      <div class="mb-1 text-sm font-semibold">Mindmap</div>
                      <pre class="max-h-56 overflow-auto">{JSON.stringify(graphSnapshot.mindmap, null, 2)}</pre>
                    </div>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        </section>
      </div>
    </div>
  </div>
</div>
