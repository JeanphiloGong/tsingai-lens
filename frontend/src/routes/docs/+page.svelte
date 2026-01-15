<script lang="ts">
  import { t } from '../_shared/i18n';
</script>

<svelte:head>
  <title>{$t('docs.pageTitle')}</title>
</svelte:head>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{$t('docs.eyebrow')}</p>
    <h1>{$t('docs.title')}</h1>
    <p class="lead">{$t('docs.lead')}</p>
    <span class="pill">{$t('docs.authNote')}</span>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">{$t('docs.quickNotesTitle')}</span>
  <h3>{$t('docs.quickNotesSub')}</h3>
  <div class="flow">
    <div class="flow-step">{$t('docs.quickNote1')}</div>
    <div class="flow-step">{$t('docs.quickNote2')}</div>
    <div class="flow-step">{$t('docs.quickNote3')}</div>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.collectionsTitle')}</h2>
    <p class="section-sub">{$t('docs.collectionsSub')}</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">POST /retrieval/collections</span>
      <h3>{$t('docs.collectionsCreateTitle')}</h3>
      <p>{$t('docs.collectionsCreateDesc')}</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/collections \
  -H "Content-Type: application/json" \
  -d '&#123;"name":"paper-lab"&#125;'</code></pre>
    </article>

    <article class="card">
      <span class="pill">GET /retrieval/collections</span>
      <h3>{$t('docs.collectionsListTitle')}</h3>
      <p>{$t('docs.collectionsListDesc')}</p>
      <pre class="code-block"><code>curl http://localhost:8010/retrieval/collections</code></pre>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.indexingTitle')}</h2>
    <p class="section-sub">{$t('docs.indexingSub')}</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">POST /retrieval/index</span>
      <h3>{$t('docs.indexTitle')}</h3>
      <p>{$t('docs.indexDesc')}</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/index \
  -H "Content-Type: application/json" \
  -d '&#123;"collection_id":"&lt;COLLECTION_ID&gt;","method":"standard","is_update_run":false,"verbose":false&#125;'</code></pre>
    </article>

    <article class="card">
      <span class="pill">POST /retrieval/index/upload</span>
      <h3>{$t('docs.indexUploadTitle')}</h3>
      <p>{$t('docs.indexUploadDesc')}</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/index/upload \
  -F "file=@/path/to/document.pdf" \
  -F "collection_id=&lt;COLLECTION_ID&gt;" \
  -F "method=standard" \
  -F "is_update_run=false" \
  -F "verbose=false"</code></pre>
    </article>

    <article class="card">
      <span class="pill">POST /retrieval/input/upload</span>
      <h3>{$t('docs.inputUploadTitle')}</h3>
      <p>{$t('docs.inputUploadDesc')}</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/input/upload \
  -F "collection_id=&lt;COLLECTION_ID&gt;" \
  -F "files=@/path/to/paper1.pdf" \
  -F "files=@/path/to/paper2.pdf"</code></pre>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.queryTitle')}</h2>
    <p class="section-sub">{$t('docs.querySub')}</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">POST /retrieval/query</span>
      <h3>{$t('docs.queryCallTitle')}</h3>
      <p>{$t('docs.queryCallDesc')}</p>
      <pre class="code-block"><code>curl -X POST http://localhost:8010/retrieval/query \
  -H "Content-Type: application/json" \
  -d '&#123;
    "collection_id":"&lt;COLLECTION_ID&gt;",
    "query":"Provide an actionable experimental plan",
    "method":"global",
    "response_type":"List of 5-7 Points",
    "include_context":false
  &#125;'</code></pre>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.graphTitle')}</h2>
    <p class="section-sub">{$t('docs.graphSub')}</p>
  </div>
  <div class="docs-grid">
    <article class="card">
      <span class="pill">GET /retrieval/graphml</span>
      <h3>{$t('docs.graphCallTitle')}</h3>
      <p>{$t('docs.graphCallDesc')}</p>
      <pre class="code-block"><code>curl -OJ "http://localhost:8010/retrieval/graphml?collection_id=&lt;COLLECTION_ID&gt;&amp;max_nodes=200&amp;min_weight=0&amp;include_community=true"</code></pre>
    </article>
  </div>
</section>

<section>
  <div class="section-header">
    <h2 class="section-title">{$t('docs.tutorialTitle')}</h2>
    <p class="section-sub">{$t('docs.tutorialSub')}</p>
  </div>
  <div class="card">
    <ol class="tutorial-list">
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep1Title')}</strong>
        <p>{$t('docs.tutorialStep1Desc1')}</p>
        <pre class="code-block"><code>snapshots:
  graphml: true</code></pre>
        <p>{$t('docs.tutorialStep1Desc2')}</p>
        <pre class="code-block"><code>embed_graph:
  enabled: true
umap:
  enabled: true</code></pre>
        <p>{$t('docs.tutorialStep1Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep2Title')}</strong>
        <p>{$t('docs.tutorialStep2Desc')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep3Title')}</strong>
        <p>{$t('docs.tutorialStep3Desc1')}</p>
        <p>{$t('docs.tutorialStep3Desc2')}</p>
        <p>{$t('docs.tutorialStep3Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep4Title')}</strong>
        <p>{$t('docs.tutorialStep4Desc1')}</p>
        <p>{$t('docs.tutorialStep4Desc2')}</p>
        <p>{$t('docs.tutorialStep4Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep5Title')}</strong>
        <p>{$t('docs.tutorialStep5Desc1')}</p>
        <p>{$t('docs.tutorialStep5Desc2')}</p>
        <p>{$t('docs.tutorialStep5Desc3')}</p>
        <p>{$t('docs.tutorialStep5Desc4')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep6Title')}</strong>
        <p>{$t('docs.tutorialStep6Desc1')}</p>
        <p>{$t('docs.tutorialStep6Desc2')}</p>
        <p>{$t('docs.tutorialStep6Desc3')}</p>
        <p>{$t('docs.tutorialStep6Desc4')}</p>
        <p>{$t('docs.tutorialStep6Desc5')}</p>
        <p>{$t('docs.tutorialStep6Desc6')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep7Title')}</strong>
        <p>{$t('docs.tutorialStep7Desc1')}</p>
        <p>{$t('docs.tutorialStep7Desc2')}</p>
        <p>{$t('docs.tutorialStep7Desc3')}</p>
        <p>{$t('docs.tutorialStep7Desc4')}</p>
        <p>{$t('docs.tutorialStep7Desc5')}</p>
        <p>{$t('docs.tutorialStep7Desc6')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep8Title')}</strong>
        <p>{$t('docs.tutorialStep8Desc1')}</p>
        <p>{$t('docs.tutorialStep8Desc2')}</p>
        <p>{$t('docs.tutorialStep8Desc3')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep9Title')}</strong>
        <p>{$t('docs.tutorialStep9Desc1')}</p>
        <p>{$t('docs.tutorialStep9Desc2')}</p>
        <p>{$t('docs.tutorialStep9Desc3')}</p>
        <p>{$t('docs.tutorialStep9Desc4')}</p>
        <p>{$t('docs.tutorialStep9Desc5')}</p>
        <p>{$t('docs.tutorialStep9Desc6')}</p>
        <p>{$t('docs.tutorialStep9Desc7')}</p>
      </li>
      <li class="tutorial-step">
        <strong>{$t('docs.tutorialStep10Title')}</strong>
        <p>{$t('docs.tutorialStep10Desc1')}</p>
        <p>{$t('docs.tutorialStep10Desc2')}</p>
        <p>{$t('docs.tutorialStep10Desc3')}</p>
      </li>
    </ol>
  </div>
</section>
