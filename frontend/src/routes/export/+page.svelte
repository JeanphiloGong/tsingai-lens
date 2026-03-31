<script lang="ts">
  import LegacyRouteNotice from '../_shared/LegacyRouteNotice.svelte';
</script>

<svelte:head>
  <title>Legacy Export Route</title>
</svelte:head>

<LegacyRouteNotice
  title="Legacy Export Route Retired"
  lead="GraphML export is no longer exposed through this old browser route."
  reason="Use the collection graph workflow for product-facing graph access. This page no longer calls the old engine-level export endpoint."
/>
