<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  sessionId: { type: String, required: true },
  meta: { type: Array, default: () => [] },
  loading: Boolean,
})
const emit = defineEmits(['generate'])

const selectedSvcIdx = ref(-1)
const selectedEvtIdx = ref(-1)
const selectedField = ref('')

const services = ref([])
const events = ref([])
const fields = ref([])

watch(() => props.meta, (val) => {
  services.value = val || []
  selectedSvcIdx.value = -1
  events.value = []
  fields.value = []
  selectedEvtIdx.value = -1
  selectedField.value = ''
}, { immediate: true })

watch(selectedSvcIdx, (idx) => {
  if (idx >= 0 && services.value[idx]) {
    events.value = services.value[idx].events || []
  } else {
    events.value = []
  }
  selectedEvtIdx.value = -1
  fields.value = []
  selectedField.value = ''
})

watch(selectedEvtIdx, (idx) => {
  if (idx >= 0 && events.value[idx]) {
    fields.value = events.value[idx].fields || []
  } else {
    fields.value = []
  }
  selectedField.value = ''
})

const svcOptions = () => services.value.map((s, i) => ({
  value: i,
  label: `${s.service_id_hex} (${s.service_id}) · ${s.events?.length || 0} events`,
}))

const evtOptions = () => events.value.map((e, i) => ({
  value: i,
  label: `${e.event_id_hex} (${e.event_id}) · ${e.fields?.length || 0} fields`,
}))

const fieldOptions = () => fields.value.map(f => ({ value: f, label: f }))

function canGenerate() {
  return selectedSvcIdx.value >= 0 && selectedEvtIdx.value >= 0 && !!selectedField.value
}

function doGenerate() {
  if (!canGenerate()) return
  const svc = services.value[selectedSvcIdx.value]
  const evt = events.value[selectedEvtIdx.value]
  emit('generate', {
    service_id: svc.service_id,
    service_label: svc.service_id_hex,
    event_id: evt.event_id,
    event_label: evt.event_id_hex,
    field_path: selectedField.value,
  })
}
</script>

<template>
  <div class="selector-bar">
    <span class="selector-label">信号选择</span>

    <select class="sel" v-model="selectedSvcIdx" :disabled="!services.length">
      <option :value="-1" disabled>-- 选择 Service --</option>
      <option v-for="(opt, i) in svcOptions()" :key="i" :value="opt.value">{{ opt.label }}</option>
    </select>

    <select class="sel" v-model="selectedEvtIdx" :disabled="!events.length">
      <option :value="-1" disabled>-- 选择 Event --</option>
      <option v-for="(opt, i) in evtOptions()" :key="i" :value="opt.value">{{ opt.label }}</option>
    </select>

    <select class="sel sel-field" v-model="selectedField" :disabled="!fields.length">
      <option value="" disabled>-- 选择字段 --</option>
      <option v-for="f in fieldOptions()" :key="f.value" :value="f.value">{{ f.label }}</option>
    </select>

    <button class="btn-gen" :disabled="!canGenerate() || loading" @click="doGenerate">
      {{ loading ? '生成中...' : '生成曲线' }}
    </button>
  </div>
</template>

<style scoped>
.selector-bar {
  display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  background: linear-gradient(180deg, #f9fbfd, #f1f5f9);
  border-bottom: 1px solid #e5ebf2; flex-shrink: 0; flex-wrap: wrap;
}
.selector-label { font-weight: 700; font-size: 14px; color: #303133; margin-right: 4px; }
.sel {
  padding: 6px 10px; border: 1px solid #d4dbe6; border-radius: 7px;
  font-size: 12px; background: #fff; outline: none; min-width: 180px;
}
.sel:focus { border-color: #409eff; box-shadow: 0 0 0 3px rgba(64,158,255,0.12); }
.sel-field { min-width: 280px; }
.btn-gen {
  padding: 7px 22px; background: #409eff; color: #fff; border: none;
  border-radius: 7px; cursor: pointer; font-size: 13px; font-weight: 600;
}
.btn-gen:disabled { background: #a0cfff; cursor: not-allowed; }
</style>
