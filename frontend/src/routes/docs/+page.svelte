<svelte:head>
  <title>Retrieval API Docs</title>
</svelte:head>

<section class="hero">
  <div class="fade-up">
    <p class="eyebrow">Docs</p>
    <h1>Retrieval API reference</h1>
    <p class="lead">
      Default base URL is http://localhost:8010. Update the host and port for deployed
      environments.
    </p>
    <span class="pill">No authentication enabled</span>
  </div>

  <div class="hero-panel fade-up delay-1">
    <p class="eyebrow">Quick notes</p>
    <h2>Behavior</h2>
    <div class="flow">
      <div class="flow-step">PDFs must contain selectable text.</div>
      <div class="flow-step">Batch import: upload inputs, then run indexing.</div>
      <div class="flow-step">GraphML export supports filters.</div>
    </div>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Indexing</h2>
    <p class="section-sub">Trigger indexing workflows from config or uploaded files.</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">POST /retrieval/index</span>
      <h3>Index from config</h3>
      <p>Run the standard indexing workflow with a config file path.</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/index \
  -H "Content-Type: application/json" \
  -d '{"config_path":"/path/to/config.yaml","method":"standard","is_update_run":false,"verbose":false}'</code></pre>
    </article>

    <article class="card">
      <span class="pill">POST /retrieval/index/upload</span>
      <h3>Upload + index</h3>
      <p>Upload a file and index using the default config.</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/index/upload \
  -F "file=@/path/to/document.pdf" \
  -F "method=standard" \
  -F "is_update_run=false" \
  -F "verbose=false"</code></pre>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Input storage</h2>
    <p class="section-sub">Upload inputs without triggering indexing.</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">POST /retrieval/input/upload</span>
      <h3>Batch input upload</h3>
      <p>Store multiple PDF or TXT files in input storage.</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/input/upload \
  -F "files=@/path/to/paper1.pdf" \
  -F "files=@/path/to/paper2.pdf"</code></pre>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Graph export</h2>
    <p class="section-sub">Download GraphML for visualization tools.</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">GET /retrieval/graphml</span>
      <h3>Export GraphML</h3>
      <p>Filter by output path, max nodes, or minimum weight.</p>
      <pre class="code-block"><code>curl -OJ "http://localhost:8010/retrieval/graphml?max_nodes=200&amp;min_weight=0"</code></pre>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">Config management</h2>
    <p class="section-sub">Upload, create, or view configuration files.</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">POST /retrieval/configs/upload</span>
      <h3>Upload config</h3>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/configs/upload \
  -F "file=@/path/to/config.yaml"</code></pre>
    </article>

    <article class="card">
      <span class="pill">POST /retrieval/configs</span>
      <h3>Create config</h3>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/configs \
  -H "Content-Type: application/json" \
  -d '{"filename":"my-config.yaml","content":"# yaml here"}'</code></pre>
    </article>

    <article class="card">
      <span class="pill">GET /retrieval/configs</span>
      <h3>List configs</h3>
      <pre class="code-block"><code>curl http://localhost:8010/retrieval/configs</code></pre>
    </article>

    <article class="card">
      <span class="pill">GET /retrieval/configs/{filename}</span>
      <h3>View config content</h3>
      <pre class="code-block"><code>curl http://localhost:8010/retrieval/configs/default.yaml</code></pre>
    </article>
  </div>
</section>
