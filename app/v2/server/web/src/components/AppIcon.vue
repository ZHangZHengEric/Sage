<script setup>
defineProps({ name: String })
const paths = {
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5',
  moon: 'M20.8 13A9 9 0 0 1 11 3.2 9 9 0 1 0 20.8 13Z',
  monitor: 'M3 4h18v13H3V4Zm9 13v4m-4 0h8',
  copy: 'M8 8h13v13H8V8ZM3 16V3h13',
  lock: 'M5 10h14v11H5V10Zm3 0V7a4 4 0 0 1 8 0v3m-4 5v2',
  help: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm-2 6a2 2 0 1 1 3 2c-1 1-1 1-1 2m0 3h.01',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Zm10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
  link: 'm10 13 4-4M8 15l-2 2a3 3 0 0 1-4-4l5-5a3 3 0 0 1 4 0m2 1 2-2a3 3 0 0 1 4 4l-5 5a3 3 0 0 1-4 0',
  trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l3 2',
  shield: 'm12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm0 5v5m0 3h.01',
  alert: 'M12 3 2 21h20L12 3Zm0 6v5m0 3h.01',
  ban: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM6 6l12 12',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  folder: 'M3 7V4h6l2 3h10v13H3V7Z',
  download: 'M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5',
  file: 'M14 2H4v20h16V8l-6-6Zm0 0v6h6M8 13h8M8 17h8',
  close: 'm6 6 12 12M6 18 18 6',
  refresh: 'M20 7a9 9 0 1 0 1 8M20 2v6h-6',

  chat: 'M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z',
  history: 'M3 12a9 9 0 1 0 2.6-6.4L3 8m0-5v5h5m4-1v5l3 2',
  agent: 'M12 3v3m-7 0h14v14H5V6ZM8 11h.01M16 11h.01M9 16h6M2 10v6m20-6v6',
  user: 'M20 21v-2a7 7 0 0 0-14 0v2M13 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
  tools: 'm14 6 4 4 3-3a6 6 0 0 1-8 8l-6 6-4-4 6-6a6 6 0 0 1 8-8l-3 3Z',
  skill: 'm13 2-9 12h7l-1 8 10-12h-7l1-8Z',
  model: 'm12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5',
  settings: 'M4 6h16M4 12h16M4 18h16M8 3v6m8 0v6m-6 0v6',
  code: 'm8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18',
  key: 'M15 3a6 6 0 1 0 0 12 6 6 0 0 0 0-12ZM10 13l-8 8m0-4 4 4m0-8 4 4',
  check: 'm5 12 4 4L19 6',
  chevron: 'm9 5 7 7-7 7',
  panel: 'M3 3h18v18H3V3Zm6 0v18',
  plus: 'M12 5v14M5 12h14',
  search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm5 12 6 6',
  grid: 'M3 3h7v7H3V3Zm11 0h7v7h-7V3ZM3 14h7v7H3v-7Zm11 0h7v7h-7v-7Z',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  logout: 'M9 3H3v18h6m6-14 5 5-5 5M8 12h12',
}
</script>
<template>
  <svg class="app-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.code" /></svg>
</template>
