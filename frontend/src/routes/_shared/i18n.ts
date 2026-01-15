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
      title: 'Connection',
      helper: 'Set the base URL once for all steps.',
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
      actionOpen: 'Open',
      actionExport: 'Export',
      actionReindex: 'Reindex',
      exporting: 'Preparing export...',
      exported: 'Export ready',
      reindexing: 'Starting index...',
      reindexStarted: 'Index started',
      noteStats: 'Status and basic metrics come from collections; deeper metrics are pending.',
      noteUpdated: 'Updated time uses created_at until updated_at is available.'
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
      title: 'Graph export',
      lead: 'Export GraphML for Gephi and other tools.',
      download: 'Download GraphML',
      downloading: 'Preparing...',
      downloaded: 'Downloaded {filename}',
      filtersTitle: 'Filter export',
      maxNodesLabel: 'Max nodes',
      minWeightLabel: 'Min weight',
      communityLabel: 'Community ID (optional)',
      includeCommunityLabel: 'Include community attribute',
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
      pageTitle: 'Retrieval API Docs',
      eyebrow: 'Docs',
      title: 'Retrieval API reference',
      lead: 'Default base URL is http://localhost:8010. Update the host and port for deployment.',
      authNote: 'No authentication enabled',
      quickNotesTitle: 'Quick notes',
      quickNotesSub: 'Behavior',
      quickNote1: 'PDFs must contain selectable text.',
      quickNote2: 'If collection_id is omitted, the default collection is used.',
      quickNote3: 'Server manages config per collection.',
      collectionsTitle: 'Collections',
      collectionsSub: 'Create and list collections.',
      collectionsCreateTitle: 'Create collection',
      collectionsCreateDesc: 'Create a new collection with an optional name.',
      collectionsListTitle: 'List collections',
      collectionsListDesc: 'Return all collections.',
      indexingTitle: 'Index & upload',
      indexingSub: 'Upload and index documents for a collection.',
      indexTitle: 'Start index',
      indexDesc: 'Trigger indexing for a collection.',
      indexUploadTitle: 'Upload + index',
      indexUploadDesc: 'Upload a file and run the index.',
      inputUploadTitle: 'Batch upload',
      inputUploadDesc: 'Upload multiple files without indexing.',
      queryTitle: 'Search',
      querySub: 'Ask questions against indexed data.',
      queryCallTitle: 'Query collection',
      queryCallDesc: 'Return an answer with optional context data.',
      graphTitle: 'Graph export',
      graphSub: 'Download GraphML with optional filters.',
      graphCallTitle: 'Export GraphML',
      graphCallDesc: 'Include community for coloring in Gephi.',
      tutorialTitle: 'Visualizing and Debugging Your Knowledge Graph',
      tutorialSub:
        'Follow this guide to visualize a knowledge graph after graphrag indexing. Adjust settings as needed.',
      tutorialStep1Title: '1. Run the pipeline',
      tutorialStep1Desc1:
        'Before building an index, review your settings.yaml configuration file and ensure that graphml snapshots are enabled.',
      tutorialStep1Desc2:
        '(Optional) Enable additional parameters to support embeddings and alternative visual tools.',
      tutorialStep1Desc3:
        'After running the indexing pipeline, there will be an output folder (defined by storage.base_dir).',
      tutorialStep2Title: '2. Locate the knowledge graph',
      tutorialStep2Desc:
        'Look for graph.graphml in the output folder. GraphML is supported by many visualization tools like Gephi.',
      tutorialStep3Title: '3. Open the graph in Gephi',
      tutorialStep3Desc1: 'Install and open Gephi.',
      tutorialStep3Desc2: 'Navigate to the output folder containing parquet files.',
      tutorialStep3Desc3:
        'Import graph.graphml to view the undirected nodes and edges.',
      tutorialStep4Title: '4. Install the Leiden Algorithm plugin',
      tutorialStep4Desc1: 'Go to Tools -> Plugins.',
      tutorialStep4Desc2: 'Search for "Leiden Algorithm".',
      tutorialStep4Desc3: 'Install the plugin and restart Gephi.',
      tutorialStep5Title: '5. Run statistics',
      tutorialStep5Desc1:
        'In Statistics, run Average Degree and Leiden Algorithm.',
      tutorialStep5Desc2: 'For Leiden, set:',
      tutorialStep5Desc3: 'Quality function: Modularity',
      tutorialStep5Desc4: 'Resolution: 1',
      tutorialStep6Title: '6. Color the graph by clusters',
      tutorialStep6Desc1: 'Go to Appearance.',
      tutorialStep6Desc2:
        'Select Nodes -> Partition and click the color palette icon.',
      tutorialStep6Desc3: 'Choose Cluster from the dropdown.',
      tutorialStep6Desc4: 'Click Palette..., then Generate....',
      tutorialStep6Desc5: 'Uncheck Limit number of colors, then Generate and Ok.',
      tutorialStep6Desc6: 'Click Apply to color by Leiden partitions.',
      tutorialStep7Title: '7. Resize nodes by degree',
      tutorialStep7Desc1: 'In Appearance, select Nodes -> Ranking.',
      tutorialStep7Desc2: 'Select the Sizing icon.',
      tutorialStep7Desc3: 'Choose Degree and set:',
      tutorialStep7Desc4: 'Min: 10',
      tutorialStep7Desc5: 'Max: 150',
      tutorialStep7Desc6: 'Click Apply.',
      tutorialStep8Title: '8. Layout the graph',
      tutorialStep8Desc1: 'In Layout, select OpenORD.',
      tutorialStep8Desc2: 'Set Liquid and Expansion to 50; others to 0.',
      tutorialStep8Desc3: 'Click Run and monitor progress.',
      tutorialStep9Title: '9. Run ForceAtlas2',
      tutorialStep9Desc1: 'Select ForceAtlas2.',
      tutorialStep9Desc2: 'Set:',
      tutorialStep9Desc3: 'Scaling: 15',
      tutorialStep9Desc4: 'Dissuade Hubs: checked',
      tutorialStep9Desc5: 'LinLog mode: uncheck',
      tutorialStep9Desc6: 'Prevent Overlap: checked',
      tutorialStep9Desc7: 'Run until nodes settle, then stop.',
      tutorialStep10Title: '10. Add text labels (optional)',
      tutorialStep10Desc1: 'Enable text labels as needed.',
      tutorialStep10Desc2: 'Resize and configure labels.',
      tutorialStep10Desc3: 'Your graph is ready for analysis.'
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
      title: '连接',
      helper: '设置一次 Base URL，全部步骤通用。',
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
      actionOpen: '打开',
      actionExport: '导出',
      actionReindex: '更新索引',
      exporting: '准备导出...',
      exported: '已完成导出',
      reindexing: '正在启动索引...',
      reindexStarted: '索引已启动',
      noteStats: '状态与基础指标来自集合接口，深度指标稍后补充。',
      noteUpdated: '未提供 updated_at 时，暂用 created_at 显示。'
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
      title: '图谱导出',
      lead: '导出 GraphML 以供 Gephi 等工具使用。',
      download: '下载 GraphML',
      downloading: '生成中...',
      downloaded: '已下载 {filename}',
      filtersTitle: '过滤导出',
      maxNodesLabel: '最大节点数',
      minWeightLabel: '最小权重',
      communityLabel: '社区 ID（可选）',
      includeCommunityLabel: '包含 community 字段',
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
      pageTitle: '检索 API 文档',
      eyebrow: '文档',
      title: '检索 API 参考',
      lead: '默认 Base URL 为 http://localhost:8010，请根据部署修改。',
      authNote: '当前未启用鉴权',
      quickNotesTitle: '快速提示',
      quickNotesSub: '注意事项',
      quickNote1: 'PDF 需可复制文本。',
      quickNote2: '未传 collection_id 时使用默认集合。',
      quickNote3: '配置由服务端按集合管理。',
      collectionsTitle: '集合管理',
      collectionsSub: '创建与列出集合。',
      collectionsCreateTitle: '创建集合',
      collectionsCreateDesc: '可选设置集合名称。',
      collectionsListTitle: '列出集合',
      collectionsListDesc: '返回全部集合。',
      indexingTitle: '索引与上传',
      indexingSub: '上传并索引集合内容。',
      indexTitle: '启动索引',
      indexDesc: '触发集合索引流程。',
      indexUploadTitle: '上传并索引',
      indexUploadDesc: '上传文件并立即索引。',
      inputUploadTitle: '批量上传',
      inputUploadDesc: '仅上传，不触发索引。',
      queryTitle: '检索',
      querySub: '对集合提出问题。',
      queryCallTitle: '检索接口',
      queryCallDesc: '返回答案，可选上下文数据。',
      graphTitle: '图谱导出',
      graphSub: '按需导出 GraphML。',
      graphCallTitle: '导出 GraphML',
      graphCallDesc: '包含 community 字段用于着色。',
      tutorialTitle: '知识图谱可视化与调试',
      tutorialSub: '跟随步骤完成 graphrag 图谱可视化。',
      tutorialStep1Title: '1. 运行流水线',
      tutorialStep1Desc1: '索引前确认 settings.yaml 已开启 graphml 快照。',
      tutorialStep1Desc2: '（可选）开启嵌入与 UMAP 等参数。',
      tutorialStep1Desc3: '索引后输出目录由 storage.base_dir 决定。',
      tutorialStep2Title: '2. 定位知识图谱',
      tutorialStep2Desc: '在输出目录找到 graph.graphml，建议用 Gephi 打开。',
      tutorialStep3Title: '3. 在 Gephi 中打开',
      tutorialStep3Desc1: '安装并打开 Gephi。',
      tutorialStep3Desc2: '进入包含 parquet 文件的输出目录。',
      tutorialStep3Desc3: '导入 graph.graphml 查看节点与边。',
      tutorialStep4Title: '4. 安装 Leiden 插件',
      tutorialStep4Desc1: '进入 Tools -> Plugins。',
      tutorialStep4Desc2: '搜索 "Leiden Algorithm"。',
      tutorialStep4Desc3: '安装后重启 Gephi。',
      tutorialStep5Title: '5. 运行统计',
      tutorialStep5Desc1: '运行 Average Degree 与 Leiden Algorithm。',
      tutorialStep5Desc2: 'Leiden 设置：',
      tutorialStep5Desc3: 'Quality function: Modularity',
      tutorialStep5Desc4: 'Resolution: 1',
      tutorialStep6Title: '6. 按社区上色',
      tutorialStep6Desc1: '进入 Appearance。',
      tutorialStep6Desc2: '选择 Nodes -> Partition 并点击调色板。',
      tutorialStep6Desc3: '下拉选择 Cluster。',
      tutorialStep6Desc4: '点击 Palette... 再 Generate....',
      tutorialStep6Desc5: '取消颜色限制，点击 Generate 与 Ok。',
      tutorialStep6Desc6: '点击 Apply 按分区上色。',
      tutorialStep7Title: '7. 按度调整大小',
      tutorialStep7Desc1: 'Appearance -> Nodes -> Ranking。',
      tutorialStep7Desc2: '选择 Sizing 图标。',
      tutorialStep7Desc3: '选择 Degree 并设置：',
      tutorialStep7Desc4: 'Min: 10',
      tutorialStep7Desc5: 'Max: 150',
      tutorialStep7Desc6: '点击 Apply。',
      tutorialStep8Title: '8. 布局图谱',
      tutorialStep8Desc1: 'Layout 中选择 OpenORD。',
      tutorialStep8Desc2: 'Liquid/Expansion 为 50，其余为 0。',
      tutorialStep8Desc3: '点击 Run 并观察。',
      tutorialStep9Title: '9. 运行 ForceAtlas2',
      tutorialStep9Desc1: '选择 ForceAtlas2。',
      tutorialStep9Desc2: '设置如下：',
      tutorialStep9Desc3: 'Scaling: 15',
      tutorialStep9Desc4: 'Dissuade Hubs: 勾选',
      tutorialStep9Desc5: 'LinLog mode: 取消勾选',
      tutorialStep9Desc6: 'Prevent Overlap: 勾选',
      tutorialStep9Desc7: '节点稳定后停止。',
      tutorialStep10Title: '10. 添加标签（可选）',
      tutorialStep10Desc1: '按需开启文本标签。',
      tutorialStep10Desc2: '调整大小与样式。',
      tutorialStep10Desc3: '完成后即可分析。'
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
