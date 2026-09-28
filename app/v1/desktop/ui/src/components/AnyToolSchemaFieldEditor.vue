<template>
  <div class="rounded-lg border bg-background p-3 space-y-3">
    <div class="flex items-center justify-between gap-2">
        <div class="font-medium text-sm">
        {{ title || `${t('tools.field') || 'Field'} ${index + 1}` }}
      </div>
      <Button
        v-if="canRemove"
        type="button"
        variant="ghost"
        size="sm"
        class="text-destructive hover:text-destructive"
        @click="$emit('remove')"
      >
        <Trash2 class="h-4 w-4 mr-2" />
        {{ t('tools.remove') || 'Remove' }}
      </Button>
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <div class="space-y-2">
        <Label class="text-xs">{{ t('tools.fieldName') || 'Name' }}</Label>
        <Input v-model="field.name" type="text" :placeholder="fieldNamePlaceholder" />
      </div>
      <div class="space-y-2">
        <Label class="text-xs">{{ t('tools.fieldType') || 'Type' }}</Label>
        <Select v-model="field.type">
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="string">string</SelectItem>
            <SelectItem value="number">number</SelectItem>
            <SelectItem value="integer">integer</SelectItem>
            <SelectItem value="boolean">boolean</SelectItem>
            <SelectItem value="object">object</SelectItem>
            <SelectItem value="array">array</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <div class="space-y-2">
        <Label class="text-xs">{{ t('tools.fieldDescription') || 'Description' }}</Label>
        <Input v-model="field.description" type="text" />
      </div>
      <div class="space-y-2">
        <Label class="text-xs">{{ t('tools.fieldDefault') || 'Default' }}</Label>
        <Input v-model="field.defaultValue" type="text" />
      </div>
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <div class="space-y-2">
        <Label class="text-xs">{{ t('tools.fieldEnum') || 'Enum values' }}</Label>
        <Textarea v-model="field.enumText" rows="3" class="font-mono text-sm" placeholder="value1&#10;value2" />
      </div>
      <div class="space-y-2">
        <Label class="text-xs">{{ t('tools.fieldMeta') || 'Meta' }}</Label>
        <div class="flex flex-wrap items-center gap-4 rounded-md border px-3 py-2">
          <div class="flex items-center gap-2">
            <Switch :checked="field.required" @update:checked="(val) => field.required = val" />
            <span class="text-xs">{{ t('tools.required') || 'Required' }}</span>
          </div>
          <div v-if="field.type === 'array'" class="flex items-center gap-2">
            <span class="text-xs text-muted-foreground">{{ t('tools.itemsType') || 'Items' }}</span>
            <Select v-model="field.itemsType">
              <SelectTrigger class="h-8 w-28"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="string">string</SelectItem>
                <SelectItem value="number">number</SelectItem>
                <SelectItem value="integer">integer</SelectItem>
                <SelectItem value="boolean">boolean</SelectItem>
                <SelectItem value="object">object</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>

    <div v-if="hasNestedSchema" class="space-y-3 rounded-xl border bg-muted/10 p-4">
      <div class="flex items-center justify-between gap-3">
        <div>
          <Label class="text-base font-medium">
            {{ nestedTitle }}
          </Label>
          <p class="text-xs text-muted-foreground">
            {{ nestedHint }}
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" @click="addNestedField">
          <Plus class="h-4 w-4 mr-2" />
          {{ t('tools.addField') || 'Add Field' }}
        </Button>
      </div>

      <div v-if="nestedFields.length === 0" class="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
        {{ t('tools.noSchemaFields') || 'No fields yet.' }}
      </div>

      <div v-for="(child, childIndex) in nestedFields" :key="child.id" class="space-y-3">
        <AnyToolSchemaFieldEditor
          :field="child"
          :index="childIndex"
          :title="`${t('tools.field') || 'Field'} ${childIndex + 1}`"
          :can-remove="true"
          @remove="removeNestedField(childIndex)"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import { useLanguage } from '@/utils/i18n.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

defineOptions({
  name: 'AnyToolSchemaFieldEditor'
})

const props = defineProps({
  field: {
    type: Object,
    required: true
  },
  index: {
    type: Number,
    default: 0
  },
  title: {
    type: String,
    default: ''
  },
  canRemove: {
    type: Boolean,
    default: true
  },
  nestingType: {
    type: String,
    default: 'properties'
  }
})

defineEmits(['remove'])

const { t } = useLanguage()

const nestedFields = computed(() => {
  if (!Array.isArray(props.field.childrenBuilder)) {
    props.field.childrenBuilder = []
  }
  return props.field.childrenBuilder
})

const hasNestedSchema = computed(() => {
  if (props.field.type === 'object') return true
  return props.field.type === 'array' && props.field.itemsType === 'object'
})

const nestedTitle = computed(() => {
  if (props.field.type === 'array') return t('tools.arrayItemsSchema') || 'Array Item Schema'
  return t('tools.nestedFields') || 'Nested Fields'
})

const nestedHint = computed(() => {
  if (props.field.type === 'array') return t('tools.arrayItemsSchemaHint') || 'Define the object schema for array items.'
  return t('tools.nestedFieldsHint') || 'Define nested object properties visually.'
})

const fieldNamePlaceholder = computed(() => {
  if (props.field.type === 'array') return 'results'
  if (props.field.type === 'object') return 'metadata'
  return 'query'
})

const createField = () => ({
  id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  name: '',
  type: 'string',
  description: '',
  required: false,
  defaultValue: '',
  enumText: '',
  itemsType: 'string',
  childrenBuilder: [],
})

const addNestedField = () => {
  if (props.field.type === 'array') {
    props.field.itemsType = 'object'
  }
  if (!Array.isArray(props.field.childrenBuilder)) {
    props.field.childrenBuilder = []
  }
  props.field.childrenBuilder.push(createField())
}

const removeNestedField = (index) => {
  if (!Array.isArray(props.field.childrenBuilder)) return
  props.field.childrenBuilder.splice(index, 1)
}
</script>
