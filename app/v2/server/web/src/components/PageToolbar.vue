<template>
  <header class="page-toolbar">
    <div v-if="$slots.default" class="page-toolbar-start"><slot /></div>
    <div v-if="$slots.actions" class="page-toolbar-actions"><slot name="actions" /></div>
    <div v-if="$slots.filters" class="page-toolbar-filters"><slot name="filters" /></div>
  </header>
</template>

<style scoped>
.page-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 18px; margin-bottom: 22px; min-width: 0; }
.page-toolbar-start { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 18px; min-width: 0; }
.page-toolbar-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-left: auto; min-width: 0; }
.page-toolbar-filters { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; gap: 12px 18px; flex: 0 0 100%; min-width: 0; }
.page-toolbar :deep(.source-tabs) { margin: 0; border: 0; }
.page-toolbar :deep(.source-tabs a) { padding: 8px 0; }
.page-toolbar :deep(.source-tabs .router-link-exact-active::after) { bottom: 0; }
.page-toolbar :deep(.model-filters), .page-toolbar :deep(.rs-filters), .page-toolbar :deep(.agent-list-filters), .page-toolbar :deep(.system-role-filters) { flex-wrap: wrap; }
.page-toolbar :deep(.rs-toolbar-actions) { gap: 9px; }
@media (max-width: 760px) {
  .page-toolbar { gap: 12px; }
  .page-toolbar-start, .page-toolbar-actions { width: 100%; }
  .page-toolbar-actions :deep(.model-search), .page-toolbar-actions :deep(.rs-search), .page-toolbar-actions :deep(.agent-search), .page-toolbar-actions :deep(.system-user-search), .page-toolbar-actions :deep(.search-input) { flex: 1 1 160px; width: auto; max-width: 100%; }
  .page-toolbar-actions :deep(.rs-toolbar-actions) { display: contents; }
}
</style>
