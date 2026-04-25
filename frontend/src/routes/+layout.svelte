<script lang="ts">
  import './layout.css';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { API_DOCS_PATH } from './_shared/base';
  import { collections } from './_shared/collections';
  import { language, t } from './_shared/i18n';
  import { themePreference } from './_shared/theme';
  import type { ThemePreference } from './_shared/theme';

  let isLangOpen = false;
  let langMenu: HTMLDivElement | null = null;
  let isThemeOpen = false;
  let themeMenu: HTMLDivElement | null = null;
  let globalSearch = '';

  function decodeRoutePart(value: string) {
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  }

  function toggleLangMenu() {
    isLangOpen = !isLangOpen;
    if (isLangOpen) {
      isThemeOpen = false;
    }
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

  function toggleThemeMenu() {
    isThemeOpen = !isThemeOpen;
    if (isThemeOpen) {
      isLangOpen = false;
    }
  }

  function closeThemeMenu() {
    isThemeOpen = false;
  }

  function setTheme(value: ThemePreference) {
    themePreference.set(value);
    isThemeOpen = false;
  }

  function handleThemeKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      closeThemeMenu();
    }
  }

  onMount(() => {
    const handleClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (isLangOpen && langMenu && !langMenu.contains(target)) {
        isLangOpen = false;
      }
      if (isThemeOpen && themeMenu && !themeMenu.contains(target)) {
        isThemeOpen = false;
      }
    };
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  });

  $: isGraphRoute = /^\/collections\/[^/]+\/graph\/?$/.test($page.url.pathname);
  $: collectionRouteMatch = /^\/collections\/([^/]+)/.exec($page.url.pathname);
  $: isCollectionRoute = Boolean(collectionRouteMatch);
  $: headerCollectionId = collectionRouteMatch?.[1]
    ? decodeRoutePart(collectionRouteMatch[1])
    : '';
  $: headerCollection = $collections.find((item) => item.id === headerCollectionId);
  $: headerCollectionName = headerCollection?.name || headerCollectionId;
</script>

<div class="app-shell">
  <div class="bg-grid" aria-hidden="true"></div>

  <header class="site-header" class:site-header--collection={isCollectionRoute}>
    <div class="header-left">
      <a class="brand" href="/">
        <div class="brand-mark">L</div>
        <div class="brand-text">
          <div class="brand-title">{$t('brand.title')}</div>
          {#if $t('brand.sub')}
            <div class="brand-sub">{$t('brand.sub')}</div>
          {/if}
        </div>
      </a>

      {#if isCollectionRoute}
        <nav class="header-breadcrumb" aria-label={$t('header.breadcrumbLabel')}>
          <a href="/">{ $t('header.breadcrumbWorkspace') }</a>
          <span aria-hidden="true">/</span>
          <a href="/">{ $t('header.breadcrumbCollection') }</a>
          <span aria-hidden="true">/</span>
          <span class="header-breadcrumb__current">{headerCollectionName}</span>
        </nav>
      {/if}
    </div>

    <form class="global-search" role="search" on:submit|preventDefault>
      <span class="global-search__icon" aria-hidden="true"></span>
      <label class="sr-only" for="global-search-input">{$t('header.globalSearchLabel')}</label>
      <input
        id="global-search-input"
        bind:value={globalSearch}
        placeholder={$t('header.globalSearchPlaceholder')}
      />
      <span class="global-search__kbd" aria-hidden="true">Ctrl K</span>
    </form>

    <div class="header-actions">
      <button class="icon-button" type="button" aria-label={$t('header.notificationsLabel')}>
        <span class="notification-icon" aria-hidden="true"></span>
      </button>
      <div
        class="theme-menu"
        bind:this={themeMenu}
        role="group"
        aria-label={$t('header.themeLabel')}
      >
        <button
          type="button"
          class="header-action"
          aria-haspopup="menu"
          aria-expanded={isThemeOpen}
          on:click|stopPropagation={toggleThemeMenu}
          on:keydown={handleThemeKeydown}
        >
          {$t('header.themeLabel')}
          <span class="theme-state">
            {#if $themePreference === 'system'}
              {$t('header.themeSystem')}
            {:else if $themePreference === 'light'}
              {$t('header.themeLight')}
            {:else}
              {$t('header.themeDark')}
            {/if}
          </span>
          <span class="chevron" aria-hidden="true">▾</span>
        </button>
        {#if isThemeOpen}
          <div class="lang-dropdown" role="menu" tabindex="-1" on:keydown={handleThemeKeydown}>
            <button type="button" role="menuitem" class:active={$themePreference === 'system'} on:click={() => setTheme('system')}>
              {$t('header.themeSystem')}
            </button>
            <button type="button" role="menuitem" class:active={$themePreference === 'light'} on:click={() => setTheme('light')}>
              {$t('header.themeLight')}
            </button>
            <button type="button" role="menuitem" class:active={$themePreference === 'dark'} on:click={() => setTheme('dark')}>
              {$t('header.themeDark')}
            </button>
          </div>
        {/if}
      </div>
      <div
        class="lang-menu"
        bind:this={langMenu}
        role="group"
        aria-label={$t('header.languageLabel')}
      >
        <button
          type="button"
          class="header-action"
          aria-haspopup="menu"
          aria-expanded={isLangOpen}
          on:click|stopPropagation={toggleLangMenu}
          on:keydown={handleLangKeydown}
        >
          {$t('header.languageLabel')}
          <span class="chevron" aria-hidden="true">▾</span>
        </button>
        {#if isLangOpen}
          <div class="lang-dropdown" role="menu" tabindex="-1" on:keydown={handleLangKeydown}>
            <button type="button" role="menuitem" class:active={$language === 'en'} on:click={() => setLanguage('en')}>
              EN
            </button>
            <button type="button" role="menuitem" class:active={$language === 'zh'} on:click={() => setLanguage('zh')}>
              中文
            </button>
          </div>
        {/if}
      </div>
      <button class="avatar-placeholder" type="button" aria-label={$t('header.userMenuLabel')}>
        <span aria-hidden="true">U</span>
      </button>
    </div>
  </header>

  <main class="page" class:page--wide={isGraphRoute}>
    <slot />
  </main>

  <footer class="site-footer">
    <a href={API_DOCS_PATH}>{$t('nav.docs')}</a>
    <span>·</span>
    <span>{$t('footer.pdfNote')}</span>
  </footer>
</div>
