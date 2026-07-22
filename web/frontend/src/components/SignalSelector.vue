<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  sessionId: { type: String, required: true },
  meta: { type: Array, default: () => [] },
  loading: Boolean,
  prefill: { type: Object, default: null },
})
const emit = defineEmits(['generate', 'clear'])

const selectedSvcIdx = ref(-1)
const selectedEvtIdx = ref(-1)
const selectedFields = ref([])
const fieldDropdownOpen = ref(false)
const fieldSearch = ref('')

let applyingPrefill = false
let generateTimer = null

const services = computed(() => props.meta || [])
const selectedService = computed(() => services.value[selectedSvcIdx.value] || null)
const events = computed(() => selectedService.value?.events || [])
const selectedEvent = computed(() => events.value[selectedEvtIdx.value] || null)
const fields = computed(() => selectedEvent.value?.fields || [])

const filteredFields = computed(() => {
  const q = fieldSearch.value.trim().toLowerCase()
  if (!q) return fields.value
  return fields.value.filter(f => f.toLowerCase().includes(q))
})

const selectedLabel = computed(() => {
  if (!selectedFields.value.length) return 'Select signal fields'
  if (selectedFields.value.length <= 2) return selectedFields.value.join(', ')
  return `${selectedFields.value.length} fields selected`
})

const pathText = computed(() => {
  if (!selectedService.value || !selectedEvent.value) return 'No signal selected'
  return `${serviceLabel(selectedService.value)} / ${eventLabel(selectedEvent.value)}`
})

const selectionReady = computed(() => {
  return Boolean(selectedService.value && selectedEvent.value && selectedFields.value.length)
})

watch(() => props.meta, () => {
  selectedSvcIdx.value = -1
  selectedEvtIdx.value = -1
  selectedFields.value = []
  fieldSearch.value = ''
  emit('clear')
}, { immediate: true })

watch(selectedSvcIdx, () => {
  if (applyingPrefill) return
  selectedEvtIdx.value = -1
  selectedFields.value = []
  fieldSearch.value = ''
  emit('clear')
})

watch(selectedEvtIdx, () => {
  if (applyingPrefill) return
  fieldSearch.value = ''
  selectedFields.value = fields.value.length ? [fields.value[0]] : []
  scheduleGenerate()
})

watch(selectedFields, () => {
  scheduleGenerate()
}, { deep: true })

// 订阅诊断页跳转时只知道 service/event。这里自动补第一个可绘制字段，
// 避免父页面需要了解字段级数据结构，保持跳转参数足够轻。
watch([() => props.prefill, services], ([pf]) => {
  if (!pf || !services.value.length) return
  applyPrefill(pf)
}, { immediate: true })

function serviceLabel(svc) {
  if (!svc) return ''
  return svc.service_name
    ? `${svc.service_id_hex} ${svc.service_name}`
    : `${svc.service_id_hex} (${svc.service_id})`
}

function eventLabel(evt) {
  if (!evt) return ''
  return evt.event_name
    ? `${evt.event_id_hex} ${evt.event_name}`
    : `${evt.event_id_hex} (${evt.event_id})`
}

function applyPrefill(pf) {
  const svcIdx = services.value.findIndex(s => Number(s.service_id) === Number(pf.service_id))
  if (svcIdx < 0) return

  applyingPrefill = true
  selectedSvcIdx.value = svcIdx

  const svcEvents = services.value[svcIdx]?.events || []
  const wantedEventId = Number(pf.event_id)
  const evtIdx = svcEvents.findIndex(e => {
    const eventId = Number(e.event_id)
    return eventId === wantedEventId || (eventId & 0x7fff) === (wantedEventId & 0x7fff)
  })

  selectedEvtIdx.value = evtIdx
  const evtFields = evtIdx >= 0 ? (svcEvents[evtIdx]?.fields || []) : []
  const requestedFields = String(pf.field_path || '')
    .split(',')
    .map(v => v.trim())
    .filter(v => evtFields.includes(v))
  selectedFields.value = requestedFields.length ? requestedFields : evtFields.slice(0, 1)
  fieldSearch.value = ''

  nextTick(() => {
    applyingPrefill = false
    scheduleGenerate()
  })
}

function toggleField(field) {
  if (selectedFields.value.includes(field)) {
    selectedFields.value = selectedFields.value.filter(f => f !== field)
  } else {
    selectedFields.value = [...selectedFields.value, field]
  }
}

function selectFirst() {
  selectedFields.value = fields.value.length ? [fields.value[0]] : []
}

function selectVisibleFields() {
  selectedFields.value = filteredFields.value.slice(0, 6)
}

function selectAllFields() {
  selectedFields.value = fields.value.slice()
}

function clearFields() {
  selectedFields.value = []
  emit('clear')
}

function scheduleGenerate() {
  window.clearTimeout(generateTimer)
  generateTimer = window.setTimeout(() => {
    if (!selectionReady.value) {
      emit('clear')
      return
    }
    doGenerate()
  }, 220)
}

function doGenerate() {
  if (!selectionReady.value) return
  fieldDropdownOpen.value = false
  emit('generate', {
    service_id: selectedService.value.service_id,
    service_label: serviceLabel(selectedService.value),
    event_id: selectedEvent.value.event_id,
    event_label: eventLabel(selectedEvent.value),
    field_path: selectedFields.value.join(','),
    field_count: selectedFields.value.length,
  })
}

function onDropdownBlur() {
  setTimeout(() => { fieldDropdownOpen.value = false }, 150)
}
</script>

<template>
  <section class="selector-panel">
    <div class="selector-main">
      <div class="selector-title">
        <span class="eyebrow">Signal Timing</span>
        <strong>{{ pathText }}</strong>
      </div>

      <div class="selector-controls">
        <label class="control">
          <span>Service</span>
          <select class="sel" v-model="selectedSvcIdx" :disabled="!services.length || loading">
            <option :value="-1" disabled>Select Service</option>
            <option v-for="(svc, i) in services" :key="svc.service_id" :value="i">
              {{ serviceLabel(svc) }} · {{ svc.events?.length || 0 }} events
            </option>
          </select>
        </label>

        <label class="control">
          <span>Event</span>
          <select class="sel" v-model="selectedEvtIdx" :disabled="!events.length || loading">
            <option :value="-1" disabled>Select Event</option>
            <option v-for="(evt, i) in events" :key="evt.event_id" :value="i">
              {{ eventLabel(evt) }} · {{ evt.fields?.length || 0 }} fields
            </option>
          </select>
        </label>

        <div class="control field-control">
          <span>Fields</span>
          <div
            class="multi-select"
            :class="{ open: fieldDropdownOpen, disabled: !fields.length || loading }"
            tabindex="0"
            @blur="onDropdownBlur"
          >
            <button class="multi-trigger" type="button" @click="fieldDropdownOpen = !fieldDropdownOpen">
              <span :class="{ placeholder: !selectedFields.length }">{{ selectedLabel }}</span>
              <span class="multi-arrow">▾</span>
            </button>
            <div class="multi-drop" v-show="fieldDropdownOpen">
              <input
                class="field-search"
                v-model="fieldSearch"
                placeholder="Filter fields"
                @click.stop
              >
              <div class="quick-row">
                <button type="button" @click.stop="selectFirst">First</button>
                <button type="button" @click.stop="selectVisibleFields">Top 6</button>
                <button type="button" @click.stop="selectAllFields">All</button>
                <button type="button" @click.stop="clearFields">Clear</button>
              </div>
              <label class="multi-item" v-for="f in filteredFields" :key="f">
                <input
                  type="checkbox"
                  :checked="selectedFields.includes(f)"
                  @change="toggleField(f)"
                >
                <span>{{ f }}</span>
              </label>
              <div class="empty-fields" v-if="fields.length && !filteredFields.length">No matched fields</div>
            </div>
          </div>
        </div>

        <button class="btn-refresh" :disabled="!selectionReady || loading" @click="doGenerate">
          {{ loading ? 'Loading' : 'Refresh' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.selector-panel {
  flex-shrink: 0;
  padding: 12px 14px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, .3);
  border-radius: 8px;
  box-shadow: 0 12px 28px rgba(15, 23, 42, .14);
}
.selector-main {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
}
.selector-title {
  min-width: 220px;
  max-width: 360px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.selector-title strong {
  color: #172033;
  font-size: 13px;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.eyebrow {
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}
.selector-controls {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(190px, 1.1fr) minmax(190px, 1.1fr) minmax(260px, 1.6fr) auto;
  gap: 10px;
  align-items: end;
  min-width: 0;
}
.control {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.control > span {
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}
.sel,
.multi-trigger,
.field-search {
  height: 34px;
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #fff;
  color: #172033;
  font-size: 12px;
  outline: none;
}
.sel {
  padding: 0 10px;
}
.sel:focus,
.multi-select.open .multi-trigger,
.field-search:focus {
  border-color: #0284c7;
  box-shadow: 0 0 0 3px rgba(2, 132, 199, .13);
}
.field-control {
  min-width: 260px;
}
.multi-select {
  position: relative;
}
.multi-select.disabled {
  opacity: .55;
  pointer-events: none;
}
.multi-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px;
  cursor: pointer;
}
.multi-trigger span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.multi-arrow {
  color: #64748b;
  font-size: 10px;
  margin-left: 8px;
}
.placeholder {
  color: #94a3b8;
}
.multi-drop {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  z-index: 120;
  max-height: 320px;
  overflow-y: auto;
  padding: 8px;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  box-shadow: 0 18px 38px rgba(15, 23, 42, .18);
}
.field-search {
  padding: 0 9px;
  margin-bottom: 7px;
}
.quick-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin-bottom: 7px;
}
.quick-row button {
  height: 26px;
  border: 1px solid #dbe3ee;
  border-radius: 6px;
  background: #f8fafc;
  color: #334155;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
}
.quick-row button:hover {
  border-color: #0284c7;
  color: #0369a1;
}
.multi-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  padding: 4px 6px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  font-family: Consolas, 'Courier New', monospace;
}
.multi-item:hover {
  background: #eef6ff;
}
.multi-item span {
  min-width: 0;
  overflow-wrap: anywhere;
}
.empty-fields {
  padding: 12px 4px;
  color: #94a3b8;
  text-align: center;
  font-size: 12px;
}
.btn-refresh {
  height: 34px;
  min-width: 88px;
  padding: 0 14px;
  border: 1px solid #0284c7;
  border-radius: 7px;
  background: #0284c7;
  color: #fff;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}
.btn-refresh:disabled {
  cursor: not-allowed;
  border-color: #bae6fd;
  background: #bae6fd;
}
@media (max-width: 1100px) {
  .selector-main {
    align-items: stretch;
    flex-direction: column;
  }
  .selector-title {
    max-width: none;
  }
  .selector-controls {
    grid-template-columns: repeat(2, minmax(180px, 1fr));
  }
}
</style>
