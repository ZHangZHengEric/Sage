<script setup>
import PageToolbar from '../components/PageToolbar.vue'
</script>

<template>
  <section class="personal-settings" aria-label="个人设置">
    <PageToolbar>
      <nav class="source-tabs" aria-label="个人设置分类">
        <router-link to="/settings/execution">执行设置</router-link>
        <router-link to="/settings/keys">API 密钥</router-link>
      </nav>
    </PageToolbar>
    <router-view />
  </section>
</template>

<style src="../developer-surfaces.css"></style>
