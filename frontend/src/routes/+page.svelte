<script lang="ts">
  import { onMount } from 'svelte';
  import { browser } from '$app/environment';

  const DEFAULT_BASE_URL = 'http://localhost:8010';

  let baseUrl = DEFAULT_BASE_URL;
  let baseStatus = '';

  let configPath = '';
  let indexMethod = 'standard';
  let indexUpdateRun = false;
  let indexVerbose = false;
  let additionalContextText = '';
  let indexConfigLoading = false;
  let indexConfigError = '';
  let indexConfigResult: unknown = null;

  let indexFile: File | null = null;
  let indexUploadMethod = 'standard';
  let indexUploadUpdateRun = false;
  let indexUploadVerbose = false;
  let indexUploadLoading = false;
  let indexUploadError = '';
  let indexUploadResult: unknown = null;

  let inputFiles: File[] = [];
  let inputUploadLoading = false;
  let inputUploadError = '';
  let inputUploadResult: unknown = null;

  let graphOutputPath = '';
  let graphMaxNodes = 200;
  let graphMinWeight = 0;
  let graphCommunityId = '';
  let graphLoading = false;
  let graphError = '';
  let graphStatus = '';

  let configsLoading = false;
  let configsError = '';
  let configsResult: unknown = null;
  let configList: string[] = [];
  let selectedConfig = '';
  let configContentLoading = false;
  let configContentError = '';
  let configContent = '';

  let newConfigFilename = '';
  let newConfigContent = '';
  let configCreateLoading = false;
  let configCreateError = '';
  let configCreateResult: unknown = null;

  let configUploadFile: File | null = null;
  let configUploadLoading = false;
  let configUploadError = '';
  let configUploadResult: unknown = null;

  onMount(() => {
    if (!browser) return;
    const stored = localStorage.getItem('retrieval.baseUrl');
    if (stored) {
      baseUrl = stored;
    }
  });

  function errorMessage(error: unknown) {
    return error instanceof Error ? error.message : 'Unexpected error.';
  }

  function formatResult(data: unknown) {
    if (data === null || data === undefined) return '';
    return typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  }

  function getBaseUrl() {
    const trimmed = baseUrl.trim();
    if (!trimmed) {
      throw new Error('Base URL is required.');
    }
    try {
      new URL(trimmed);
    } catch {
      throw new Error('Base URL must be a valid URL.');
    }
    return trimmed.replace(/\/$/, '');
  }

  function saveBaseUrl() {
    const trimmed = baseUrl.trim();
    if (!trimmed) {
      baseStatus = 'Base URL is required.';
      return;
    }
    try {
      new URL(trimmed);
    } catch {
      baseStatus = 'Base URL must be a valid URL.';
      return;
    }
    baseUrl = trimmed;
    if (browser) {
      localStorage.setItem('retrieval.baseUrl', trimmed);
    }
    baseStatus = 'Saved for this browser.';
    window.setTimeout(() => {
      baseStatus = '';
    }, 2200);
  }

  function resetBaseUrl() {
    baseUrl = DEFAULT_BASE_URL;
    if (browser) {
      localStorage.setItem('retrieval.baseUrl', DEFAULT_BASE_URL);
    }
    baseStatus = 'Reset to default.';
    window.setTimeout(() => {
      baseStatus = '';
    }, 2200);
  }

  async function requestJson(path: string, init: RequestInit = {}) {
    const url = `${getBaseUrl()}${path}`;
    const headers = new Headers(init.headers ?? {});
    if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(url, { ...init, headers });
    const text = await response.text();
    const data = text ? parseMaybeJson(text) : null;
    if (!response.ok) {
      const detail = typeof data === 'string' ? data : JSON.stringify(data);
      throw new Error(`${response.status} ${response.statusText}${detail ? ` - ${detail}` : ''}`);
    }
    return data;
  }

  async function requestText(path: string, init: RequestInit = {}) {
    const url = `${getBaseUrl()}${path}`;
    const response = await fetch(url, init);
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
    }
    return text;
  }

  function parseMaybeJson(value: string) {
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  }

  function handleIndexFileChange(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    indexFile = target.files?.[0] ?? null;
  }

  function handleInputFilesChange(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    inputFiles = target.files ? Array.from(target.files) : [];
  }

  function handleConfigUploadChange(event: Event) {
    const target = event.currentTarget as HTMLInputElement;
    configUploadFile = target.files?.[0] ?? null;
  }

  async function submitIndexConfig(event: SubmitEvent) {
    event.preventDefault();
    indexConfigError = '';
    indexConfigResult = null;

    const trimmedPath = configPath.trim();
    if (!trimmedPath) {
      indexConfigError = 'Config path is required.';
      return;
    }

    let additionalContext: unknown = undefined;
    if (additionalContextText.trim()) {
      try {
        additionalContext = JSON.parse(additionalContextText);
      } catch {
        indexConfigError = 'Additional context must be valid JSON.';
        return;
      }
    }

    indexConfigLoading = true;
    try {
      const payload: Record<string, unknown> = {
        config_path: trimmedPath,
        method: indexMethod,
        is_update_run: indexUpdateRun,
        verbose: indexVerbose
      };
      if (additionalContext !== undefined) {
        payload.additional_context = additionalContext;
      }
      indexConfigResult = await requestJson('/retrieval/index', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
    } catch (error) {
      indexConfigError = errorMessage(error);
    } finally {
      indexConfigLoading = false;
    }
  }

  async function submitIndexUpload(event: SubmitEvent) {
    event.preventDefault();
    indexUploadError = '';
    indexUploadResult = null;

    if (!indexFile) {
      indexUploadError = 'Select a file to upload.';
      return;
    }

    const formData = new FormData();
    formData.append('file', indexFile);
    formData.append('method', indexUploadMethod);
    formData.append('is_update_run', String(indexUploadUpdateRun));
    formData.append('verbose', String(indexUploadVerbose));

    indexUploadLoading = true;
    try {
      indexUploadResult = await requestJson('/retrieval/index/upload', {
        method: 'POST',
        body: formData
      });
    } catch (error) {
      indexUploadError = errorMessage(error);
    } finally {
      indexUploadLoading = false;
    }
  }

  async function submitInputUpload(event: SubmitEvent) {
    event.preventDefault();
    inputUploadError = '';
    inputUploadResult = null;

    if (!inputFiles.length) {
      inputUploadError = 'Select one or more files.';
      return;
    }

    const formData = new FormData();
    inputFiles.forEach((file) => formData.append('files', file));

    inputUploadLoading = true;
    try {
      inputUploadResult = await requestJson('/retrieval/input/upload', {
        method: 'POST',
        body: formData
      });
    } catch (error) {
      inputUploadError = errorMessage(error);
    } finally {
      inputUploadLoading = false;
    }
  }

  async function downloadGraph() {
    graphError = '';
    graphStatus = '';
    graphLoading = true;

    try {
      const params = new URLSearchParams();
      if (graphOutputPath.trim()) {
        params.set('output_path', graphOutputPath.trim());
      }
      const maxNodes = Number.isFinite(graphMaxNodes) ? graphMaxNodes : 200;
      const minWeight = Number.isFinite(graphMinWeight) ? graphMinWeight : 0;
      params.set('max_nodes', String(maxNodes));
      params.set('min_weight', String(minWeight));
      if (graphCommunityId.trim()) {
        params.set('community_id', graphCommunityId.trim());
      }

      const url = `${getBaseUrl()}/retrieval/graphml?${params.toString()}`;
      const response = await fetch(url);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
      }
      const blob = await response.blob();
      const fileName = `graph-${Date.now()}.graphml`;
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(objectUrl);
      graphStatus = `Downloaded ${fileName}`;
    } catch (error) {
      graphError = errorMessage(error);
    } finally {
      graphLoading = false;
    }
  }

  async function loadConfigs() {
    configsError = '';
    configsResult = null;
    configList = [];
    selectedConfig = '';

    configsLoading = true;
    try {
      const data = await requestJson('/retrieval/configs', { method: 'GET' });
      configsResult = data;
      if (Array.isArray(data)) {
        configList = data.map(String);
      } else if (data && typeof data === 'object') {
        const record = data as Record<string, unknown>;
        const list = record.configs ?? record.items ?? record.files ?? [];
        if (Array.isArray(list)) {
          configList = list.map(String);
        }
      }
    } catch (error) {
      configsError = errorMessage(error);
    } finally {
      configsLoading = false;
    }
  }

  async function loadConfigContent() {
    configContentError = '';
    configContent = '';

    if (!selectedConfig) {
      configContentError = 'Select a config to view.';
      return;
    }

    configContentLoading = true;
    try {
      const content = await requestText(`/retrieval/configs/${encodeURIComponent(selectedConfig)}`);
      configContent = content;
    } catch (error) {
      configContentError = errorMessage(error);
    } finally {
      configContentLoading = false;
    }
  }

  async function createConfig(event: SubmitEvent) {
    event.preventDefault();
    configCreateError = '';
    configCreateResult = null;

    if (!newConfigFilename.trim()) {
      configCreateError = 'Filename is required.';
      return;
    }

    if (!newConfigContent.trim()) {
      configCreateError = 'Content is required.';
      return;
    }

    configCreateLoading = true;
    try {
      configCreateResult = await requestJson('/retrieval/configs', {
        method: 'POST',
        body: JSON.stringify({
          filename: newConfigFilename.trim(),
          content: newConfigContent
        })
      });
    } catch (error) {
      configCreateError = errorMessage(error);
    } finally {
      configCreateLoading = false;
    }
  }

  async function uploadConfig(event: SubmitEvent) {
    event.preventDefault();
    configUploadError = '';
    configUploadResult = null;

    if (!configUploadFile) {
      configUploadError = 'Select a config file to upload.';
      return;
    }

    const formData = new FormData();
    formData.append('file', configUploadFile);

    configUploadLoading = true;
    try {
      configUploadResult = await requestJson('/retrieval/configs/upload', {
        method: 'POST',
        body: formData
      });
    } catch (error) {
      configUploadError = errorMessage(error);
    } finally {
      configUploadLoading = false;
    }
  }
</script>

<svelte:head>
  <title>Retrieval Console</title>
</svelte:head>

<section class="hero">
  <div class="fade-up">
    <p class="eyebrow">Retrieval Console</p>
    <h1>Index, map, and export your knowledge graph.</h1>
    <p class="lead">
      A single workspace to upload inputs, run indexing jobs, and export GraphML from the
      retrieval backend.
    </p>
    <div class="flow">
      <div class="flow-step">1. Upload input files</div>
      <div class="flow-step">2. Run indexing</div>
      <div class="flow-step">3. Export GraphML</div>
    </div>
  </div>

  <div class="hero-panel fade-up delay-1">
    <div>
      <p class="eyebrow">Connection</p>
      <h2>Base API URL</h2>
      <p class="lead">Default is local; change it per deployment.</p>
    </div>
    <div class="field">
      <label for="base-url">Base URL</label>
      <input
        id="base-url"
        class="input"
        bind:value={baseUrl}
        placeholder={DEFAULT_BASE_URL}
        autocomplete="url"
      />
    </div>
    <div class="toggle-row">
      <button class="btn btn--primary" type="button" on:click={saveBaseUrl}>Save</button>
      <button class="btn btn--ghost" type="button" on:click={resetBaseUrl}>Use default</button>
    </div>
    {#if baseStatus}
      <div class="status" role="status" aria-live="polite">{baseStatus}</div>
    {/if}
    <span class="pill">No auth required</span>
  </div>
</section>

<section class="card fade-up delay-2">
  <h3>Batch import flow</h3>
  <p>Recommended order for large uploads.</p>
  <div class="flow">
    <div class="flow-step">POST /retrieval/input/upload</div>
    <div class="flow-step">POST /retrieval/index</div>
    <div class="flow-step">GET /retrieval/graphml</div>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Indexing</h2>
    <p class="section-sub">Start indexing from a config file or upload a document directly.</p>
  </div>
  <div class="grid">
    <div class="card fade-up">
      <span class="pill">POST /retrieval/index</span>
      <h3>Index with config</h3>
      <p>Run an indexing workflow based on an existing config file.</p>
      <form on:submit={submitIndexConfig}>
        <div class="field">
          <label for="config-path">Config path</label>
          <input
            id="config-path"
            class="input"
            bind:value={configPath}
            placeholder="/path/to/config.yaml"
            required
          />
        </div>
        <div class="field">
          <label for="index-method">Method</label>
          <select id="index-method" class="select" bind:value={indexMethod}>
            <option value="standard">standard</option>
            <option value="fast">fast</option>
            <option value="standard-update">standard-update</option>
            <option value="fast-update">fast-update</option>
          </select>
        </div>
        <div class="field">
          <label for="additional-context">Additional context (JSON)</label>
          <textarea
            id="additional-context"
            class="textarea"
            bind:value={additionalContextText}
            placeholder={'{"project":"alpha"}'}
          ></textarea>
        </div>
        <div class="toggle-row">
          <label>
            <input type="checkbox" bind:checked={indexUpdateRun} />
            Update run
          </label>
          <label>
            <input type="checkbox" bind:checked={indexVerbose} />
            Verbose
          </label>
        </div>
        <button class="btn btn--primary" type="submit" disabled={indexConfigLoading}>
          {indexConfigLoading ? 'Running...' : 'Start index'}
        </button>
      </form>
      {#if indexConfigError}
        <div class="status status--error" role="alert">{indexConfigError}</div>
      {/if}
      {#if indexConfigResult !== null}
        <pre class="code-block">{formatResult(indexConfigResult)}</pre>
      {/if}
    </div>

    <div class="card fade-up delay-1">
      <span class="pill">POST /retrieval/index/upload</span>
      <h3>Upload file + index</h3>
      <p>Upload a PDF or TXT and run the default indexing config.</p>
      <form on:submit={submitIndexUpload}>
        <div class="field">
          <label for="index-file">File</label>
          <input id="index-file" class="input" type="file" on:change={handleIndexFileChange} />
        </div>
        <div class="field">
          <label for="index-upload-method">Method</label>
          <select id="index-upload-method" class="select" bind:value={indexUploadMethod}>
            <option value="standard">standard</option>
            <option value="fast">fast</option>
            <option value="standard-update">standard-update</option>
            <option value="fast-update">fast-update</option>
          </select>
        </div>
        <div class="toggle-row">
          <label>
            <input type="checkbox" bind:checked={indexUploadUpdateRun} />
            Update run
          </label>
          <label>
            <input type="checkbox" bind:checked={indexUploadVerbose} />
            Verbose
          </label>
        </div>
        <button class="btn btn--primary" type="submit" disabled={indexUploadLoading}>
          {indexUploadLoading ? 'Uploading...' : 'Upload + index'}
        </button>
      </form>
      {#if indexUploadError}
        <div class="status status--error" role="alert">{indexUploadError}</div>
      {/if}
      {#if indexUploadResult !== null}
        <pre class="code-block">{formatResult(indexUploadResult)}</pre>
      {/if}
    </div>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Input storage</h2>
    <p class="section-sub">Upload multiple files without triggering indexing.</p>
  </div>
  <div class="grid">
    <div class="card fade-up">
      <span class="pill">POST /retrieval/input/upload</span>
      <h3>Batch upload</h3>
      <p>Store multiple files in input storage for later indexing.</p>
      <form on:submit={submitInputUpload}>
        <div class="field">
          <label for="input-files">Files</label>
          <input
            id="input-files"
            class="input"
            type="file"
            multiple
            on:change={handleInputFilesChange}
          />
        </div>
        <button class="btn btn--primary" type="submit" disabled={inputUploadLoading}>
        {inputUploadLoading
          ? 'Uploading...'
          : `Upload${inputFiles.length ? ` (${inputFiles.length})` : ''}`}
        </button>
      </form>
      {#if inputUploadError}
        <div class="status status--error" role="alert">{inputUploadError}</div>
      {/if}
      {#if inputUploadResult !== null}
        <pre class="code-block">{formatResult(inputUploadResult)}</pre>
      {/if}
    </div>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Graph export</h2>
    <p class="section-sub">Download GraphML for Gephi or other graph tools.</p>
  </div>
  <div class="grid">
    <div class="card fade-up">
      <span class="pill">GET /retrieval/graphml</span>
      <h3>Export GraphML</h3>
      <p>Filter by node count, weight, or community.</p>
      <div class="field">
        <label for="graph-output">Output path (optional)</label>
        <input id="graph-output" class="input" bind:value={graphOutputPath} placeholder="/path" />
      </div>
      <div class="field">
        <label for="graph-max">Max nodes</label>
        <input id="graph-max" class="input" type="number" bind:value={graphMaxNodes} min="1" />
      </div>
      <div class="field">
        <label for="graph-weight">Min weight</label>
        <input id="graph-weight" class="input" type="number" bind:value={graphMinWeight} step="0.1" />
      </div>
      <div class="field">
        <label for="graph-community">Community ID (optional)</label>
        <input id="graph-community" class="input" bind:value={graphCommunityId} />
      </div>
      <button class="btn btn--primary" type="button" on:click={downloadGraph} disabled={graphLoading}>
        {graphLoading ? 'Preparing...' : 'Download GraphML'}
      </button>
      {#if graphError}
        <div class="status status--error" role="alert">{graphError}</div>
      {/if}
      {#if graphStatus}
        <div class="status" role="status" aria-live="polite">{graphStatus}</div>
      {/if}
    </div>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Config management</h2>
    <p class="section-sub">List, inspect, and create indexing configurations.</p>
  </div>
  <div class="grid">
    <div class="card fade-up">
      <span class="pill">GET /retrieval/configs</span>
      <h3>List configs</h3>
      <p>Load available config files from the backend.</p>
      <button class="btn btn--primary" type="button" on:click={loadConfigs} disabled={configsLoading}>
        {configsLoading ? 'Loading...' : 'Load configs'}
      </button>
      {#if configsError}
        <div class="status status--error" role="alert">{configsError}</div>
      {/if}
      {#if configList.length}
        <div class="list">
          {#each configList as config}
            <button
              type="button"
              class="btn btn--ghost list-button"
              class:active={selectedConfig === config}
              on:click={() => (selectedConfig = config)}
            >
              {config}
            </button>
          {/each}
        </div>
      {:else if configsResult !== null}
        <pre class="code-block">{formatResult(configsResult)}</pre>
      {/if}
      <div class="divider"></div>
      <button class="btn btn--ghost" type="button" on:click={loadConfigContent}>
        View selected config
      </button>
      {#if configContentLoading}
        <div class="status" role="status" aria-live="polite">Loading config...</div>
      {/if}
      {#if configContentError}
        <div class="status status--error" role="alert">{configContentError}</div>
      {/if}
      {#if configContent}
        <pre class="code-block">{configContent}</pre>
      {/if}
    </div>

    <div class="card fade-up delay-1">
      <span class="pill">POST /retrieval/configs</span>
      <h3>Create config</h3>
      <p>Create a new config from raw YAML content.</p>
      <form on:submit={createConfig}>
        <div class="field">
          <label for="config-filename">Filename</label>
          <input
            id="config-filename"
            class="input"
            bind:value={newConfigFilename}
            placeholder="my-config.yaml"
            required
          />
        </div>
        <div class="field">
          <label for="config-content">Content</label>
          <textarea
            id="config-content"
            class="textarea"
            bind:value={newConfigContent}
            placeholder="# yaml here"
          ></textarea>
        </div>
        <button class="btn btn--primary" type="submit" disabled={configCreateLoading}>
          {configCreateLoading ? 'Saving...' : 'Create config'}
        </button>
      </form>
      {#if configCreateError}
        <div class="status status--error" role="alert">{configCreateError}</div>
      {/if}
      {#if configCreateResult !== null}
        <pre class="code-block">{formatResult(configCreateResult)}</pre>
      {/if}
    </div>

    <div class="card fade-up delay-2">
      <span class="pill">POST /retrieval/configs/upload</span>
      <h3>Upload config</h3>
      <p>Upload a config file as multipart form data.</p>
      <form on:submit={uploadConfig}>
        <div class="field">
          <label for="config-upload">Config file</label>
          <input
            id="config-upload"
            class="input"
            type="file"
            on:change={handleConfigUploadChange}
          />
        </div>
        <button class="btn btn--primary" type="submit" disabled={configUploadLoading}>
          {configUploadLoading ? 'Uploading...' : 'Upload config'}
        </button>
      </form>
      {#if configUploadError}
        <div class="status status--error" role="alert">{configUploadError}</div>
      {/if}
      {#if configUploadResult !== null}
        <pre class="code-block">{formatResult(configUploadResult)}</pre>
      {/if}
    </div>
  </div>
</section>
