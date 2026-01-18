import { browser } from '$app/environment';
import { derived, writable } from 'svelte/store';

export type Language = 'en' | 'zh';

type Translations = Record<string, string | Translations>;

const translations: Record<Language, Translations> = {
  en: {
    brand: {
      title: 'Lens',
      sub: ''
    },
    nav: {
      home: 'Collections',
      docs: 'Docs',
      system: 'System'
    },
    header: {
      authNone: 'Auth: none',
      languageLabel: 'Language'
    },
    footer: {
      pdfNote: 'PDFs must contain selectable text. Scanned PDFs are not supported.'
    },
    connection: {
      title: 'Base URL',
      helper: 'Set the base URL used for all requests.',
      baseUrlLabel: 'Base URL',
      save: 'Save',
      reset: 'Reset',
      saved: 'Saved',
      resetStatus: 'Reset to default'
    },
    home: {
      eyebrow: 'Workspace',
      title: 'Collections',
      lead: 'Start with a collection. Upload papers, index, ask questions, export graphs.',
      primaryAction: 'Create collection',
      emptyTitle: 'No collections yet',
      emptyDesc: 'Create a collection to upload papers and build a knowledge graph.',
      emptyCta: 'Create your first collection',
      loading: 'Loading collections...',
      tableName: 'Collection',
      tableStatus: 'Status',
      tableDocs: 'Docs',
      tableEntities: 'Entities',
      tableUpdated: 'Updated',
      tableActions: 'Actions',
      statusUnknown: 'Unknown',
      statusReady: 'Ready',
      statusEmpty: 'Empty',
      metricsPlaceholder: 'Pending API',
      updatedPlaceholder: '—',
      actionExport: 'Export',
      actionIndex: 'Index',
      actionReindex: 'Reindex',
      actionDelete: 'Delete',
      exporting: 'Preparing export...',
      exported: 'Export ready',
      indexing: 'Starting full index...',
      indexStarted: 'Full index started',
      reindexing: 'Starting index...',
      reindexStarted: 'Index started',
      openRowLabel: 'Open collection {name}',
      deleteTitle: 'Delete collection',
      deleteDesc: 'Delete "{name}" and all outputs. This cannot be undone.',
      deleteConfirm: 'Delete',
      deleteDeleting: 'Deleting...',
      deleteCancel: 'Cancel',
      deleteDisabled: 'Default collection cannot be deleted.',
      noteStats: '',
      noteUpdated: ''
    },
    create: {
      title: 'Create collection',
      nameLabel: 'Collection name',
      namePlaceholder: 'paper-lab',
      descLabel: 'Description (optional)',
      descPlaceholder: 'Short description',
      descHelper: 'Description is not stored yet (API not available).',
      defaultConfigLabel: 'Use default configuration',
      defaultConfigHelper: 'Advanced config is managed server-side.',
      submit: 'Create',
      creating: 'Creating...',
      cancel: 'Cancel',
      errorName: 'Please enter a collection name.'
    },
    collection: {
      eyebrow: 'Collection',
      idLabel: 'ID',
      unknownName: 'Untitled collection',
      tabs: {
        overview: 'Overview',
        documents: 'Documents',
        search: 'Search',
        graph: 'Graph',
        reports: 'Reports',
        settings: 'Settings'
      },
      backToCollections: 'Back to collections'
    },
    overview: {
      title: 'Collection overview',
      lead: 'Track progress and jump to the next action.',
      statusLabel: 'Status',
      statusUnknown: 'Unknown (API pending)',
      statusReady: 'Ready',
      statusEmpty: 'Empty',
      metricPapers: 'Papers',
      metricEntities: 'Entities',
      metricRelations: 'Relations',
      metricCommunities: 'Communities',
      metricNote: 'Relations and community counts appear when metrics APIs are available.',
      nextActionsTitle: 'Next actions',
      nextSearch: 'Ask a question',
      nextExport: 'Export GraphML',
      nextUpload: 'Upload papers'
    },
    documents: {
      title: 'Documents',
      lead: 'Upload new papers and trigger indexing when you are ready.',
      addFiles: 'Add files',
      modalTitle: 'Add documents',
      modalLead: 'Drop PDFs or TXT files to upload.',
      dropHint: 'Drop files here or click to browse.',
      browse: 'Browse files',
      selectedCount: 'Selected {count} file(s).',
      indexAfterLabel: 'Index immediately after upload',
      indexModeLabel: 'Indexing mode',
      indexModeUpdate: 'Incremental update (recommended)',
      indexModeRebuild: 'Full rebuild',
      methodLabel: 'Method',
      methodStandard: 'standard',
      methodFast: 'fast',
      upload: 'Upload',
      uploading: 'Uploading...',
      uploadDone: 'Upload complete',
      indexing: 'Indexing started',
      indexDone: 'Indexing complete',
      listTitle: 'Document list',
      listPlaceholder: 'Document status API is not available yet.',
      listHelper: 'Uploads will still index correctly even without list data.',
      errorNoFiles: 'Select one or more files.'
    },
    search: {
      title: 'Search',
      lead: 'Ask a focused question and review evidence-backed results.',
      inputLabel: 'Question',
      placeholder: 'Ask a question about the collection...',
      submit: 'Search',
      searching: 'Searching...',
      exampleText: 'Summarize the most actionable experimental steps in these papers.',
      advanced: 'Advanced options',
      methodLabel: 'Method',
      responseTypeLabel: 'Response type',
      communityLevelLabel: 'Community level',
      includeContextLabel: 'Include evidence context',
      dynamicCommunityLabel: 'Dynamic community selection',
      verboseLabel: 'Verbose output',
      resultTitle: 'Results',
      summaryTitle: 'Summary',
      evidenceTitle: 'Evidence',
      communitiesTitle: 'Related communities',
      noEvidence: 'No evidence was returned in this response.',
      rawContext: 'Context data',
      rawResponse: 'Raw response',
      errorNoQuery: 'Enter a question to search.'
    },
    graph: {
      title: 'Graph',
      lead: 'Preview, search, and export your collection graph.',
      previewTitle: 'Graph preview',
      previewLead: 'Load a preview to search, filter, and color by community.',
      previewLoad: 'Load preview',
      previewLoading: 'Loading preview...',
      previewLoaded: 'Preview loaded',
      previewStatusClose: 'Dismiss',
      previewEmpty: 'No preview loaded yet.',
      previewCanvasLabel: 'Graph preview canvas',
      searchLabel: 'Search nodes',
      searchPlaceholder: 'Search by name or ID',
      communityFilterLabel: 'Community filter',
      communityAll: 'All communities',
      colorByCommunityLabel: 'Color by community',
      resetFilters: 'Reset filters',
      layoutRun: 'Re-run layout',
      layoutDone: 'Layout updated',
      visibleNodes: 'Visible nodes',
      visibleEdges: 'Visible edges',
      exportImage: 'Export PNG',
      imageExported: 'Image exported',
      download: 'Download GraphML',
      downloading: 'Preparing...',
      downloaded: 'Downloaded {filename}',
      filtersTitle: 'Export filters',
      filtersNote: 'Filters apply to export and preview load.',
      maxNodesLabel: 'Max nodes',
      minWeightLabel: 'Min weight',
      communityLabel: 'Community ID (optional)',
      includeCommunityLabel: 'Include community attribute',
      previewTipNoCommunity: 'Community attribute missing. Re-export with Include community attribute.',
      statsTitle: 'Graph stats',
      statsPlaceholder: 'Graph metrics API not available yet.',
      tipsTitle: 'Gephi tips',
      tip1: 'Import graph.graphml and run Leiden for clustering.',
      tip2: 'Use Partition to color clusters and Ranking to size by degree.',
      tip3: 'Run OpenORD, then ForceAtlas2 for layout.'
    },
    reports: {
      title: 'Reports',
      lead: 'Community summaries and trends will appear here.',
      placeholder: 'Reports API is not available yet.'
    },
    settings: {
      title: 'Settings',
      lead: 'Collection-level settings are managed on the server.',
      defaultConfigLabel: 'Use default configuration',
      defaultConfigHelper: 'Settings are read-only in the current API.',
      advancedTitle: 'Advanced settings',
      advancedHelper: 'LLM, embeddings, clustering, and layout options will appear here.',
      placeholder: 'Settings API is not available yet.'
    },
    system: {
      title: 'System',
      lead: 'Run history and logs will appear here.',
      placeholder: 'System logs API is not available yet.'
    },
    docs: {
      pageTitle: 'Lens Guide',
      eyebrow: 'Docs',
      title: 'Using Lens',
      lead: 'Everything happens in the web interface: collections, indexing, search, and graph export.',
      quickNotesTitle: 'Quick notes',
      quickNotesSub: 'Before you start',
      quickNote1: 'PDFs must contain selectable text.',
      quickNote2: 'Collections keep papers, searches, and exports together.',
      quickNote3: 'Indexing can run immediately after upload or later from Documents.',
      workflowTitle: 'Core workflow',
      workflowSub: 'One clear action per step.',
      workflowCreateTitle: 'Create a collection',
      workflowCreateDesc: 'From Collections, click Create collection and name it.',
      workflowUploadTitle: 'Upload documents',
      workflowUploadDesc: 'Open the collection, go to Documents, and add PDF/TXT files.',
      workflowIndexTitle: 'Build the index',
      workflowIndexDesc: 'Choose whether to index immediately; status turns Ready when finished.',
      workflowSearchTitle: 'Ask questions',
      workflowSearchDesc: 'Use Search to get evidence-backed answers.',
      workflowGraphTitle: 'Export the graph',
      workflowGraphDesc: 'Open Graph to download GraphML and filter nodes if needed.',
      navTitle: 'Collection tabs',
      navSub: 'Each tab focuses on one job.',
      navOverview: 'Overview: status and next actions.',
      navDocuments: 'Documents: upload and indexing controls.',
      navSearch: 'Search: ask a question and review evidence.',
      navGraph: 'Graph: export GraphML and view tips.',
      navReports: 'Reports: summary view when available.',
      navSettings: 'Settings: read-only configuration for now.',
      navNote: 'Some tabs may appear read-only until related features are enabled.',
      tutorialTitle: 'Visualizing Your Knowledge Graph (Gephi)',
      tutorialSub: 'Export GraphML from the web UI and explore it in Gephi.',
      tutorialStep1Title: '1. Build a collection graph',
      tutorialStep1Desc1: 'Create a collection, upload documents, and run indexing in Documents.',
      tutorialStep1Desc2: 'Wait until the collection status shows Ready.',
      tutorialStep2Title: '2. Export GraphML',
      tutorialStep2Desc:
        'Open Graph, set Max nodes/Min weight, keep Include community attribute on, then download.',
      tutorialStep3Title: '3. Open in Gephi',
      tutorialStep3Desc1: 'Install and open Gephi.',
      tutorialStep3Desc2: 'Import the downloaded .graphml file.',
      tutorialStep4Title: '4. Install the Leiden plugin',
      tutorialStep4Desc1: 'Go to Tools -> Plugins.',
      tutorialStep4Desc2: 'Search for Leiden Algorithm.',
      tutorialStep4Desc3: 'Install and restart Gephi.',
      tutorialStep5Title: '5. Run statistics',
      tutorialStep5Desc1: 'Run Average Degree and Leiden Algorithm.',
      tutorialStep5Desc2: 'For Leiden, set: Modularity, Resolution 1.',
      tutorialStep6Title: '6. Color by communities',
      tutorialStep6Desc1: 'Go to Appearance -> Nodes -> Partition.',
      tutorialStep6Desc2: 'Choose community and generate a palette.',
      tutorialStep6Desc3: 'Click Apply to color the graph.',
      tutorialStep6Desc4: 'If community is missing, re-export with Include community attribute.',
      tutorialStep7Title: '7. Resize by degree',
      tutorialStep7Desc1: 'Go to Appearance -> Nodes -> Ranking.',
      tutorialStep7Desc2: 'Use Degree with Min 10 and Max 150.',
      tutorialStep7Desc3: 'Click Apply.',
      tutorialStep8Title: '8. Layout with OpenORD',
      tutorialStep8Desc1: 'In Layout, select OpenORD.',
      tutorialStep8Desc2: 'Set Liquid and Expansion to 50; others to 0.',
      tutorialStep8Desc3: 'Run and stop when it stabilizes.',
      tutorialStep9Title: '9. Refine with ForceAtlas2',
      tutorialStep9Desc1: 'Select ForceAtlas2.',
      tutorialStep9Desc2:
        'Scaling 15; Dissuade Hubs checked; Prevent Overlap checked; LinLog mode off.',
      tutorialStep9Desc3: 'Run until nodes settle, then stop.',
      tutorialStep10Title: '10. Add labels',
      tutorialStep10Desc1: 'Enable labels and adjust size for readability.',
      tutorialStep10Desc2: 'Your graph is ready for analysis.'
    },
    error: {
      baseUrlRequired: 'Base URL is required.',
      baseUrlInvalid: 'Base URL must be a valid URL.',
      unexpected: 'Unexpected error.'
    }
  },
  zh: {
    brand: {
      title: 'Lens',
      sub: ''
    },
    nav: {
      home: '集合',
      docs: '文档',
      system: '系统'
    },
    header: {
      authNone: '鉴权：无',
      languageLabel: '语言'
    },
    footer: {
      pdfNote: 'PDF 需可复制文本，扫描版暂不支持。'
    },
    connection: {
      title: 'Base URL',
      helper: '设置所有请求使用的 Base URL。',
      baseUrlLabel: 'Base URL',
      save: '保存',
      reset: '重置',
      saved: '已保存',
      resetStatus: '已重置为默认'
    },
    home: {
      eyebrow: '工作区',
      title: '集合',
      lead: '从集合开始，上传、索引、检索、导出图谱。',
      primaryAction: '创建集合',
      emptyTitle: '暂无集合',
      emptyDesc: '创建集合以上传论文并构建知识图谱。',
      emptyCta: '创建第一个集合',
      loading: '正在加载集合...',
      tableName: '集合名称',
      tableStatus: '状态',
      tableDocs: '文档数',
      tableEntities: '实体数',
      tableUpdated: '最近更新',
      tableActions: '操作',
      statusUnknown: '未知',
      statusReady: '可用',
      statusEmpty: '空',
      metricsPlaceholder: '等待接口',
      updatedPlaceholder: '—',
      actionExport: '导出',
      actionIndex: '索引',
      actionReindex: '更新索引',
      actionDelete: '删除',
      exporting: '准备导出...',
      exported: '已完成导出',
      indexing: '正在启动全量索引...',
      indexStarted: '全量索引已启动',
      reindexing: '正在启动索引...',
      reindexStarted: '索引已启动',
      openRowLabel: '打开集合 {name}',
      deleteTitle: '删除集合',
      deleteDesc: '将删除“{name}”及其全部输出文件，且无法撤销。',
      deleteConfirm: '确认删除',
      deleteDeleting: '删除中...',
      deleteCancel: '取消',
      deleteDisabled: '默认集合不可删除。',
      noteStats: '',
      noteUpdated: ''
    },
    create: {
      title: '创建集合',
      nameLabel: '集合名称',
      namePlaceholder: 'paper-lab',
      descLabel: '描述（可选）',
      descPlaceholder: '简要说明',
      descHelper: '描述暂不保存（接口未提供）。',
      defaultConfigLabel: '使用默认配置',
      defaultConfigHelper: '高级配置由服务端管理。',
      submit: '创建',
      creating: '创建中...',
      cancel: '取消',
      errorName: '请输入集合名称。'
    },
    collection: {
      eyebrow: '集合',
      idLabel: 'ID',
      unknownName: '未命名集合',
      tabs: {
        overview: '概览',
        documents: '文档',
        search: '检索',
        graph: '图谱',
        reports: '报告',
        settings: '设置'
      },
      backToCollections: '返回集合列表'
    },
    overview: {
      title: '集合概览',
      lead: '查看状态并前往下一步。',
      statusLabel: '状态',
      statusUnknown: '未知（等待接口）',
      statusReady: '可用',
      statusEmpty: '空',
      metricPapers: '论文数',
      metricEntities: '实体数',
      metricRelations: '关系数',
      metricCommunities: '社区数',
      metricNote: '关系与社区指标需等待统计接口支持。',
      nextActionsTitle: '下一步',
      nextSearch: '开始检索',
      nextExport: '导出 GraphML',
      nextUpload: '上传论文'
    },
    documents: {
      title: '文档',
      lead: '上传论文，并在需要时触发索引。',
      addFiles: '添加文件',
      modalTitle: '添加文档',
      modalLead: '拖拽 PDF/TXT 到此处上传。',
      dropHint: '拖拽文件或点击浏览。',
      browse: '选择文件',
      selectedCount: '已选择 {count} 个文件。',
      indexAfterLabel: '上传后立即索引',
      indexModeLabel: '索引方式',
      indexModeUpdate: '增量更新（推荐）',
      indexModeRebuild: '全量重建',
      methodLabel: '方法',
      methodStandard: 'standard',
      methodFast: 'fast',
      upload: '上传',
      uploading: '上传中...',
      uploadDone: '上传完成',
      indexing: '索引已启动',
      indexDone: '索引完成',
      listTitle: '文档列表',
      listPlaceholder: '文档状态接口尚未提供。',
      listHelper: '即使没有列表，也可以正常索引。',
      errorNoFiles: '请选择一个或多个文件。'
    },
    search: {
      title: '检索',
      lead: '提出清晰问题，获取基于证据的结果。',
      inputLabel: '问题',
      placeholder: '输入你想查询的问题...',
      submit: '检索',
      searching: '检索中...',
      exampleText: '基于这些论文给出可执行的实验步骤。',
      advanced: '高级选项',
      methodLabel: '方法',
      responseTypeLabel: '输出格式',
      communityLevelLabel: '社区层级',
      includeContextLabel: '包含证据上下文',
      dynamicCommunityLabel: '动态社区选择',
      verboseLabel: '详细输出',
      resultTitle: '结果',
      summaryTitle: '结论摘要',
      evidenceTitle: '证据列表',
      communitiesTitle: '关联社区',
      noEvidence: '本次响应未返回证据数据。',
      rawContext: '上下文数据',
      rawResponse: '原始响应',
      errorNoQuery: '请输入检索问题。'
    },
    graph: {
      title: '图谱',
      lead: '预览、检索并导出集合图谱。',
      previewTitle: '图谱预览',
      previewLead: '加载预览后可搜索、筛选并按社区上色。',
      previewLoad: '加载预览',
      previewLoading: '预览加载中...',
      previewLoaded: '预览已加载',
      previewStatusClose: '关闭',
      previewEmpty: '尚未加载预览。',
      previewCanvasLabel: '图谱预览画布',
      searchLabel: '搜索节点',
      searchPlaceholder: '按名称或 ID 搜索',
      communityFilterLabel: '社区筛选',
      communityAll: '全部社区',
      colorByCommunityLabel: '按社区上色',
      resetFilters: '重置筛选',
      layoutRun: '重新布局',
      layoutDone: '布局已更新',
      visibleNodes: '可见节点',
      visibleEdges: '可见边',
      exportImage: '导出 PNG',
      imageExported: '图片已导出',
      download: '下载 GraphML',
      downloading: '生成中...',
      downloaded: '已下载 {filename}',
      filtersTitle: '导出筛选',
      filtersNote: '筛选会影响导出与预览加载。',
      maxNodesLabel: '最大节点数',
      minWeightLabel: '最小权重',
      communityLabel: '社区 ID（可选）',
      includeCommunityLabel: '包含 community 字段',
      previewTipNoCommunity: '未包含 community 字段，请勾选后重新导出或预览。',
      statsTitle: '图谱摘要',
      statsPlaceholder: '图谱统计接口尚未提供。',
      tipsTitle: 'Gephi 提示',
      tip1: '导入 graph.graphml 后运行 Leiden 聚类。',
      tip2: 'Partition 上色、Ranking 按度设置大小。',
      tip3: '先 OpenORD，再 ForceAtlas2 布局。'
    },
    reports: {
      title: '报告',
      lead: '社区总结与规律将在此展示。',
      placeholder: '报告接口尚未提供。'
    },
    settings: {
      title: '设置',
      lead: '集合级设置由服务端管理。',
      defaultConfigLabel: '使用默认配置',
      defaultConfigHelper: '当前接口下配置为只读。',
      advancedTitle: '高级设置',
      advancedHelper: 'LLM、Embeddings、聚类与布局配置稍后开放。',
      placeholder: '设置接口尚未提供。'
    },
    system: {
      title: '系统',
      lead: '运行记录与日志将在此展示。',
      placeholder: '系统日志接口尚未提供。'
    },
    docs: {
      pageTitle: 'Lens 使用指南',
      eyebrow: '文档',
      title: '如何使用 Lens',
      lead: '所有流程都在 Web 界面完成：创建集合、上传、索引、检索与图谱导出。',
      quickNotesTitle: '快速提示',
      quickNotesSub: '开始前',
      quickNote1: 'PDF 需可复制文本，扫描版不支持。',
      quickNote2: '集合是论文、检索与导出的工作区。',
      quickNote3: '上传后可立即索引，也可稍后在“文档”中触发。',
      workflowTitle: '核心流程',
      workflowSub: '一步一动作。',
      workflowCreateTitle: '创建集合',
      workflowCreateDesc: '在集合页点击“创建集合”，填写名称即可。',
      workflowUploadTitle: '上传文档',
      workflowUploadDesc: '进入集合的“文档”，批量添加 PDF/TXT。',
      workflowIndexTitle: '构建索引',
      workflowIndexDesc: '可选择上传后立即索引；完成后状态显示为“可用”。',
      workflowSearchTitle: '开始检索',
      workflowSearchDesc: '在“检索”输入问题，查看基于证据的答案。',
      workflowGraphTitle: '导出图谱',
      workflowGraphDesc: '在“图谱”下载 GraphML，可按节点数/权重过滤。',
      navTitle: '集合页签',
      navSub: '每个页签只做一件事。',
      navOverview: '概览：状态与下一步建议。',
      navDocuments: '文档：上传与索引操作。',
      navSearch: '检索：提出问题并查看证据。',
      navGraph: '图谱：导出 GraphML 与可视化建议。',
      navReports: '报告：汇总视图（可用时显示）。',
      navSettings: '设置：当前为只读配置。',
      navNote: '部分页签为占位内容，将随功能上线而开放。',
      tutorialTitle: '知识图谱可视化（Gephi）',
      tutorialSub: '通过 Web 界面导出 GraphML，并在 Gephi 中分析结构。',
      tutorialStep1Title: '1. 构建集合图谱',
      tutorialStep1Desc1: '创建集合，上传文档，并在“文档”里完成索引。',
      tutorialStep1Desc2: '状态显示为“可用”后再进行导出。',
      tutorialStep2Title: '2. 导出 GraphML',
      tutorialStep2Desc: '进入“图谱”，按需设置最大节点/最小权重，保持“包含 community 字段”开启，然后下载。',
      tutorialStep3Title: '3. 在 Gephi 中打开',
      tutorialStep3Desc1: '安装并打开 Gephi。',
      tutorialStep3Desc2: '导入刚下载的 .graphml 文件。',
      tutorialStep4Title: '4. 安装 Leiden 插件',
      tutorialStep4Desc1: '进入 Tools -> Plugins。',
      tutorialStep4Desc2: '搜索 Leiden Algorithm 并安装。',
      tutorialStep4Desc3: '重启 Gephi。',
      tutorialStep5Title: '5. 运行统计',
      tutorialStep5Desc1: '运行 Average Degree 与 Leiden Algorithm。',
      tutorialStep5Desc2: 'Leiden 设置：Modularity；Resolution 1。',
      tutorialStep6Title: '6. 按社区上色',
      tutorialStep6Desc1: 'Appearance -> Nodes -> Partition。',
      tutorialStep6Desc2: '选择 community 并生成调色板。',
      tutorialStep6Desc3: '点击 Apply 进行上色。',
      tutorialStep6Desc4: '若看不到 community，请回到图谱页重新导出。',
      tutorialStep7Title: '7. 按度调整大小',
      tutorialStep7Desc1: 'Appearance -> Nodes -> Ranking。',
      tutorialStep7Desc2: '选择 Degree 并设置 Min 10、Max 150。',
      tutorialStep7Desc3: '点击 Apply。',
      tutorialStep8Title: '8. 使用 OpenORD 布局',
      tutorialStep8Desc1: 'Layout 中选择 OpenORD。',
      tutorialStep8Desc2: 'Liquid 与 Expansion 设为 50，其余为 0。',
      tutorialStep8Desc3: '运行并观察，稳定后停止。',
      tutorialStep9Title: '9. 用 ForceAtlas2 精调',
      tutorialStep9Desc1: '选择 ForceAtlas2。',
      tutorialStep9Desc2: 'Scaling 15；勾选 Dissuade Hubs 与 Prevent Overlap；LinLog 关闭。',
      tutorialStep9Desc3: '运行至节点稳定后停止。',
      tutorialStep10Title: '10. 添加标签',
      tutorialStep10Desc1: '按需开启标签并调整大小。',
      tutorialStep10Desc2: '图谱即可用于分析。'
    },
    error: {
      baseUrlRequired: 'Base URL 不能为空。',
      baseUrlInvalid: 'Base URL 格式不正确。',
      unexpected: '发生未知错误。'
    }
  }
};

function format(template: string, vars: Record<string, string | number> = {}) {
  return template.replace(/\{(\w+)\}/g, (_, key) => String(vars[key] ?? ''));
}

function lookupTranslation(lang: Language, key: string) {
  const parts = key.split('.');
  let value: Translations | string | undefined = translations[lang];
  for (const part of parts) {
    if (!value || typeof value !== 'object' || !(part in value)) {
      return null;
    }
    value = (value as Translations)[part];
  }
  return typeof value === 'string' ? value : null;
}

export function translateKey(lang: Language, key: string, vars?: Record<string, string | number>) {
  const template = lookupTranslation(lang, key) ?? lookupTranslation('en', key) ?? key;
  return format(template, vars);
}

function detectLanguage(): Language {
  if (!browser) return 'en';
  const stored = localStorage.getItem('retrieval.lang');
  if (stored === 'en' || stored === 'zh') return stored;
  const browserLang = navigator.language.toLowerCase();
  return browserLang.startsWith('zh') ? 'zh' : 'en';
}

export const language = writable<Language>(detectLanguage());

if (browser) {
  language.subscribe((value) => {
    localStorage.setItem('retrieval.lang', value);
  });
}

export const t = derived(language, ($language) => {
  return (key: string, vars?: Record<string, string | number>) => translateKey($language, key, vars);
});
