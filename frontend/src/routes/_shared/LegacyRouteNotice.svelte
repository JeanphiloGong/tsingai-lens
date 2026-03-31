<script lang="ts">
  import { API_DOCS_PATH } from './base';

  export let eyebrow = 'Legacy Route';
  export let title = 'Legacy page retired';
  export let lead =
    'This route is no longer part of the supported browser workflow.';
  export let reason =
    'Use the collection workflow for product-facing actions, or open API docs for the current contract.';
</script>

<section class="hero hero--simple">
  <div class="fade-up">
    <p class="eyebrow">{eyebrow}</p>
    <h1>{title}</h1>
    <p class="lead">{lead}</p>
  </div>
</section>

<section class="card fade-up">
  <span class="pill">Legacy Route</span>
  <h3>Use collections instead</h3>
  <p>{reason}</p>
</section>

<div class="step-actions">
  <a class="btn btn--ghost" href="/">Open collections</a>
  <a class="btn btn--primary" href={API_DOCS_PATH}>Open API docs</a>
</div>
