<script lang="ts">
  import LegacyRouteNotice from '../_shared/LegacyRouteNotice.svelte';
</script>

<svelte:head>
  <title>Legacy Index Route</title>
</svelte:head>

<LegacyRouteNotice
  title="Legacy Index Route Retired"
  lead="Build runs start from each collection workspace."
  reason="The product-facing frontend no longer exposes the old engine-level build launcher in the browser. Start processing from a collection instead."
/>
