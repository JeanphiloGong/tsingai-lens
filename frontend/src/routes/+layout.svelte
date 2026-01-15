<script lang="ts">
  import './layout.css';
  import { page } from '$app/stores';
</script>

<div class="app-shell">
  <div class="bg-shape bg-shape--one" aria-hidden="true"></div>
  <div class="bg-shape bg-shape--two" aria-hidden="true"></div>
  <div class="bg-grid" aria-hidden="true"></div>

  <header class="site-header">
    <div class="brand">
      <div class="brand-mark">R</div>
      <div class="brand-text">
        <div class="brand-title">Retrieval Studio</div>
        <div class="brand-sub">Index, store, export</div>
      </div>
    </div>

    <nav class="nav">
      <a href="/" class:active={$page.url.pathname === '/'}>Console</a>
      <a href="/docs" class:active={$page.url.pathname.startsWith('/docs')}>Docs</a>
    </nav>

    <div class="header-meta">
      <span class="badge">Auth: none</span>
      <span class="meta-text">Base URL configurable</span>
    </div>
  </header>

  <main class="page">
    <slot />
  </main>

  <footer class="site-footer">
    PDFs must contain selectable text. Scanned PDFs are not supported.
  </footer>
</div>
