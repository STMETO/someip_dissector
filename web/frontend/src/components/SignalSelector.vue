<script setup>
import { ref, watch, computed } from 'vue'

const props = defineProps({
  sessionId: { type: String, required: true },
  meta: { type: Array, default: () => [] },
  loading: Boolean,
  prefill: { type: Object, default: null },
})
const emit = defineEmits(['generate'])

const selectedSvcIdx = ref(-1)
const selectedEvtIdx = ref(-1)
const selectedFields = ref([])
const fieldDropdownOpen = ref(false)

const services = ref([])
const events = ref([])
const fields = ref([])

watch(() => props.meta, (val) => {
  services.value = val || []
  selectedSvcIdx.value = -1
  events.value = []; fields.value = []
  selectedEvtIdx.value = -1; selectedFields.value = []
}, { immediate: true })

watch(selectedSvcIdx, (idx) => {
  if (idx >= 0 && services.value[idx]) {
    events.value = services.value[idx].events || []
  } else { events.value = [] }
  selectedEvtIdx.value = -1; fields.value = []; selectedFields.value = []
})

watch(selectedEvtIdx, (idx) => {
  if (idx >= 0 && events.value[idx]) {
    fields.value = events.value[idx].fields || []
  } else { fields.value = [] }
  selectedFields.value = []
})

// 从诊断页跳转时预选
watch([() => props.prefill, () => props.meta], ([pf]) => {
  if (!pf || !services.value.length) return
  const svcIdx = services.value.findIndex(s => s.service_id === pf.service_id)
  if (svcIdx >= 0) {
    selectedSvcIdx.value = svcIdx
    const evts = services.value[svcIdx].events || []
    const evtIdx = evts.findIndex(e => e.event_id === pf.event_id)
    if (evtIdx >= 0) selectedEvtIdx.value = evtIdx
  }
})

const svcOptions = () => services.value.map((s, i) => ({
  value: i,
  label: s.service_name
    ? `${s.service_id_hex} ${s.service_name} · ${s.events?.length || 0} events`
    : `${s.service_id_hex} (${s.service_id}) · ${s.events?.length || 0} events`,
}))

const evtOptions = () => events.value.map((e, i) => ({
  value: i,
  label: e.event_name
    ? `${e.event_id_hex} ${e.event_name} · ${e.fields?.length || 0} fields`
    : `${e.event_id_hex} (${e.event_id}) · ${e.fields?.length || 0} fields`,
}))

const selectedLabel = computed(() => {
  if (!selectedFields.value.length) return '-- 选择字段（可多选） --'
  if (selectedFields.value.length <= 2) return selectedFields.value.join(', ')
  return `${selectedFields.value.length} 个字段已选`
})

const dropdownWidth = computed(() => {
  const maxLen = fields.value.reduce((m, f) => Math.max(m, f.length), 0)
  // 每个字符约 8px（monospace 12px），加 checkbox + padding
  return Math.max(260, maxLen * 9 + 40) + 'px'
})

function toggleAllFields() {
  if (selectedFields.value.length === fields.value.length) {
    selectedFields.value = []
  } else {
    selectedFields.value = fields.value.slice()
  }
}

function canGenerate() {
  return selectedSvcIdx.value >= 0 && selectedEvtIdx.value >= 0 && selectedFields.value.length > 0
}

function doGenerate() {
  if (!canGenerate()) return
  const svc = services.value[selectedSvcIdx.value]
  const evt = events.value[selectedEvtIdx.value]
  fieldDropdownOpen.value = false
  emit('generate', {
    service_id: svc.service_id,
    service_label: svc.service_id_hex,
    event_id: evt.event_id,
    event_label: evt.event_id_hex,
    field_path: selectedFields.value.join(','),
  })
}

// 点击外部关闭下拉
function onDropdownBlur() {
  setTimeout(() => { fieldDropdownOpen.value = false }, 150)
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

    <!-- 多选字段下拉 -->
    <div class="multi-select" :class="{ open: fieldDropdownOpen, disabled: !fields.length }"
         :style="{ width: dropdownWidth }" tabindex="0" @blur="onDropdownBlur">
      <div class="multi-trigger" @click="fieldDropdownOpen = !fieldDropdownOpen">
        <span :class="{ placeholder: !selectedFields.length }">{{ selectedLabel }}</span>
        <span class="multi-arrow">▾</span>
      </div>
      <div class="multi-drop" v-show="fieldDropdownOpen">
        <label class="multi-item" v-if="fields.length > 1" @click.stop="toggleAllFields">
          <input type="checkbox" :checked="selectedFields.length === fields.length" @click.stop>
          <span class="multi-all">全选 / 取消</span>
        </label>
        <label class="multi-item" v-for="f in fields" :key="f">
          <input type="checkbox" :value="f" v-model="selectedFields">
          <span>{{ f }}</span>
        </label>
      </div>
    </div>

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
/* ---- 多选下拉 ---- */
.multi-select { position: relative; min-width: 340px; }
.multi-select.disabled { opacity: 0.5; pointer-events: none; }
.multi-trigger {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 10px; border: 1px solid #d4dbe6; border-radius: 7px;
  font-size: 12px; background: #fff; cursor: pointer; min-height: 32px;
}
.multi-select.open .multi-trigger { border-color: #409eff; box-shadow: 0 0 0 3px rgba(64,158,255,0.12); }
.multi-arrow { font-size: 10px; color: #909399; margin-left: 6px; }
.placeholder { color: #c0c4cc; }
.multi-drop {
  position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
  max-height: 260px; overflow-y: auto; background: #fff;
  border: 1px solid #d4dbe6; border-radius: 7px; margin-top: 2px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.1);
}
.multi-item {
  display: flex; align-items: center; gap: 8px; padding: 5px 10px;
  font-size: 12px; cursor: pointer; font-family: 'Consolas','Courier New',monospace;
}
.multi-item:hover { background: #f0f7ff; }
.multi-item input[type="checkbox"] { cursor: pointer; }
.multi-all { color: #409eff; font-weight: 600; }
.btn-gen {
  padding: 7px 22px; background: #409eff; color: #fff; border: none;
  border-radius: 7px; cursor: pointer; font-size: 13px; font-weight: 600;
}
.btn-gen:disabled { background: #a0cfff; cursor: not-allowed; }
</style>
