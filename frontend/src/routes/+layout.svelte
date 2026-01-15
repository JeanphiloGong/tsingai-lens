<script lang="ts">
  import './layout.css';
  import { page } from '$app/stores';
  import ConnectionBar from './_shared/ConnectionBar.svelte';
  import { language, t } from './_shared/i18n';
</script>

<div class="app-shell">
  <div class="bg-shape bg-shape--one" aria-hidden="true"></div>
  <div class="bg-shape bg-shape--two" aria-hidden="true"></div>
  <div class="bg-grid" aria-hidden="true"></div>

  <header class="site-header">
    <div class="brand">
      <div class="brand-mark">R</div>
      <div class="brand-text">
        <div class="brand-title">{$t('brand.title')}</div>
        <div class="brand-sub">{$t('brand.sub')}</div>
      </div>
    </div>

    <nav class="nav">
      <a href="/" class:active={$page.url.pathname === '/'}>{$t('nav.home')}</a>
      <a href="/docs" class:active={$page.url.pathname.startsWith('/docs')}>{$t('nav.docs')}</a>
      <a href="/system" class:active={$page.url.pathname.startsWith('/system')}>{$t('nav.system')}</a>
    </nav>

    <div class="header-meta">
      <span class="badge">{$t('header.authNone')}</span>
      <div class="lang-toggle" role="group" aria-label={$t('header.languageLabel')}>
        <button
          type="button"
          class:active={$language === 'en'}
          on:click={() => language.set('en')}
        >
          EN
        </button>
        <button
          type="button"
          class:active={$language === 'zh'}
          on:click={() => language.set('zh')}
        >
          中文
        </button>
      </div>
    </div>
  </header>

  <main class="page">
    <ConnectionBar />
    <slot />
  </main>

  <footer class="site-footer">
    {$t('footer.pdfNote')}
  </footer>
</div>
