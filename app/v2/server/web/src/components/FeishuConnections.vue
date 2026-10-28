<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api.js'
import AppIcon from './AppIcon.vue'
import FeishuConnectionForm from './FeishuConnectionForm.vue'
import FeishuConnectionDetail from './FeishuConnectionDetail.vue'

const connections = ref([]), selected = ref(''), loading = ref(true), error = ref(''), message = ref(''), creating = ref(false)
const current = computed(() => connections.value.find(item => item.id === selected.value))
let disposed = false, sequence = 0
onBeforeUnmount(() => { disposed = true; sequence++ })
async function load(preferred = selected.value) {
  const request = ++sequence
  loading.value = true; error.value = ''
  try {
    const page = await api.imConnections()
    if (disposed || request !== sequence) return
    connections.value = page.items.map(item => {
      const current = connections.value.find(value => value.id === item.id)
      return current && (current.revision > item.revision || (current.revision === item.revision && current.paired && !item.paired)) ? current : item
    })
    selected.value = page.items.some(item => item.id === preferred) ? preferred : page.items[0]?.id || ''
  } catch (exc) { if (!disposed && request === sequence) error.value = exc.message }
  finally { if (!disposed && request === sequence) loading.value = false }
}
function changed(value) { connections.value = connections.value.map(item => item.id === value.id ? value : item) }
function invalidateListRead() { sequence++; loading.value = false; error.value = '' }
function created(value) {
  invalidateListRead()
  connections.value = [...connections.value.filter(item => item.id !== value.id), value]; selected.value = value.id; message.value = '连接已创建'
}
function removed(id) {
  invalidateListRead()
  connections.value = connections.value.filter(item => item.id !== id)
  selected.value = connections.value[0]?.id || ''; message.value = '连接已删除'
}
onMounted(() => load())
</script>
<template>
  <article class="system-inspector im-inspector" aria-label="飞书连接管理">
    <div class="system-inspector-content">
      <header class="inspector-head"><div><AppIcon name="chat" /><h1>飞书</h1></div><div class="im-actions"><button class="btn ghost" type="button" :disabled="loading" @click="load()">刷新连接</button><button class="btn cta" type="button" @click="creating = true"><AppIcon name="plus" />添加连接</button></div></header>
      <p v-if="message" class="system-message" role="status"><span>{{ message }}</span><button class="icon-button" type="button" aria-label="关闭提示" @click="message = ''"><AppIcon name="close" /></button></p>
      <div v-if="error" class="system-error" role="alert"><span>{{ error }}</span><button class="btn ghost" type="button" :disabled="loading" @click="load()">重新加载</button></div>
      <div v-if="loading && !connections.length" class="system-skeleton" aria-busy="true" aria-label="正在加载飞书连接"><i v-for="n in 3" :key="n"></i></div>
      <template v-else-if="connections.length">
        <div class="im-connection-picker"><label for="im-connection">连接</label><select id="im-connection" v-model="selected"><option v-for="item in connections" :key="item.id" :value="item.id">{{ item.name }}{{ item.credentials_error ? '（不可用）' : !item.enabled ? '（已停用）' : item.paired ? '' : '（待配对）' }}</option></select></div>
        <FeishuConnectionDetail v-if="current" :key="current.id" :connection="current" @changed="changed" @removed="removed" />
      </template>
      <div v-else-if="!error" class="im-empty-state"><AppIcon name="chat" /><h2>暂无飞书连接</h2><button class="btn cta" type="button" @click="creating = true">添加连接</button></div>
    </div>
    <FeishuConnectionForm v-model="creating" @created="created" />
  </article>
</template>
<style src="../im-connections.css"></style>
