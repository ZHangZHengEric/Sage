<template>
  <Dialog :open="open" @update:open="handleOpenChange">
    <DialogContent class="sm:max-w-[420px]">
      <DialogHeader>
        <DialogTitle>{{ titleText }}</DialogTitle>
        <DialogDescription>{{ message }}</DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button variant="outline" @click="cancel">{{ t('common.cancel') }}</Button>
        <Button @click="confirm">{{ t('common.confirm') }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { useLanguage } from '@/utils/i18n'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter
} from '@/components/ui/dialog'

const { t } = useLanguage()
const open = ref(false)
const message = ref('')
const title = ref('')
const resolver = ref(null)

const titleText = computed(() => title.value || t('common.confirm'))

const resolvePending = (value) => {
  if (resolver.value) {
    resolver.value(value)
    resolver.value = null
  }
}

const ask = (msg, options = {}) => {
  message.value = msg
  title.value = options.title || ''
  open.value = true
  return new Promise((resolve) => {
    resolver.value = resolve
  })
}

const confirm = () => {
  open.value = false
  resolvePending(true)
}

const cancel = () => {
  open.value = false
  resolvePending(false)
}

const handleOpenChange = (value) => {
  open.value = value
  if (!value) {
    resolvePending(false)
  }
}

onBeforeUnmount(() => {
  resolvePending(false)
})

defineExpose({
  confirm: ask
})
</script>
