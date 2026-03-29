<script lang="ts">
  import LegacyRouteNotice from '../_shared/LegacyRouteNotice.svelte';
</script>

<svelte:head>
  <title>Legacy Config Routes</title>
</svelte:head>

<LegacyRouteNotice
  title="Legacy Config Routes Retired"
  lead="The current app-layer frontend does not expose browser config management endpoints."
  reason="These routes are retired to avoid calling unsupported engine-level paths. Use the collection workflow for product tasks, or open /api/docs for the current backend contract."
/>
