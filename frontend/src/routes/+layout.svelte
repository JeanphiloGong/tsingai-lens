<script lang="ts">
  import './layout.css';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import ConnectionBar from './_shared/ConnectionBar.svelte';
  import { language, t } from './_shared/i18n';

  let isLangOpen = false;
  let langMenu: HTMLDivElement | null = null;

  function toggleLangMenu() {
    isLangOpen = !isLangOpen;
  }

  function closeLangMenu() {
    isLangOpen = false;
  }

  function setLanguage(value: 'en' | 'zh') {
    language.set(value);
    isLangOpen = false;
  }

  function handleLangKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeLangMenu();
    }
  }

  onMount(() => {
    const handleClick = (event: MouseEvent) => {
      if (!isLangOpen) return;
      const target = event.target as Node;
      if (langMenu && !langMenu.contains(target)) {
        isLangOpen = false;
      }
    };
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  });
</script>

<div class="app-shell">
  <div class="bg-shape bg-shape--one" aria-hidden="true"></div>
  <div class="bg-shape bg-shape--two" aria-hidden="true"></div>
  <div class="bg-grid" aria-hidden="true"></div>

  <header class="site-header">
    <a class="brand" href="/">
      <div class="brand-mark">L</div>
      <div class="brand-text">
        <div class="brand-title">{$t('brand.title')}</div>
        {#if $t('brand.sub')}
          <div class="brand-sub">{$t('brand.sub')}</div>
        {/if}
      </div>
    </a>

    <div class="header-actions">
      <a class="header-action" href="/docs" class:active={$page.url.pathname.startsWith('/docs')}>
        {$t('nav.docs')}
      </a>
      <ConnectionBar />
      <div
        class="lang-menu"
        bind:this={langMenu}
        on:keydown={handleLangKeydown}
        aria-label={$t('header.languageLabel')}
      >
        <button
          type="button"
          class="header-action"
          aria-haspopup="menu"
          aria-expanded={isLangOpen}
          on:click|stopPropagation={toggleLangMenu}
        >
          {$t('header.languageLabel')}
          <span class="chevron" aria-hidden="true">▾</span>
        </button>
        {#if isLangOpen}
          <div class="lang-dropdown" role="menu">
            <button type="button" role="menuitem" class:active={$language === 'en'} on:click={() => setLanguage('en')}>
              EN
            </button>
            <button type="button" role="menuitem" class:active={$language === 'zh'} on:click={() => setLanguage('zh')}>
              中文
            </button>
          </div>
        {/if}
      </div>
    </div>
  </header>

  <main class="page">
    <slot />
  </main>

  <footer class="site-footer">
    {$t('footer.pdfNote')}
  </footer>
</div>
