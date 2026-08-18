<script setup>
import { computed, ref, watch } from 'vue'
import SignalSelector from './SignalSelector.vue'
import SignalChart from './SignalChart.vue'
import { fetchSignalMeta, fetchSignalData } from '../api'

const props = defineProps({
  sessionId: { type: String, required: true },
  prefill: { type: Object, default: null },
  theme: { type: String, default: 'light' },
})
const emit = defineEmits(['navigate-message'])

const meta = ref([])
const loading = ref(false)
const chartData = ref(null)
const selectInfo = ref(null)
const errorText = ref('')

let requestSerial = 0

const chartStats = computed(() => {
  const fields = chartData.value?.fields || []
  const pointCount = fields.reduce((sum, f) => sum + (f.points?.length || 0), 0)
  const transitionCount = fields.reduce((sum, f) => sum + (f.transitions?.length || 0), 0)
  return {
    fields: fields.length,
    points: pointCount,
    transitions: transitionCount,
  }
})

watch(() => props.sessionId, (sid) => {
  if (sid) loadMeta(sid)
}, { immediate: true })

async function loadMeta(sid) {
  meta.value = []
  chartData.value = null
  selectInfo.value = null
  errorText.value = ''
  try {
    meta.value = await fetchSignalMeta(sid)
  } catch {
    meta.value = []
    errorText.value = 'Failed to load signal metadata'
  }
}

async function onGenerate(params) {
  const serial = ++requestSerial
  loading.value = true
  errorText.value = ''
  selectInfo.value = params

  try {
    const result = await fetchSignalData(
      props.sessionId,
      params.service_id,
      params.event_id,
      params.field_path,
    )
    if (serial === requestSerial) chartData.value = result
  } catch {
    if (serial === requestSerial) {
      chartData.value = null
      errorText.value = 'Failed to load signal data'
    }
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

function onClear() {
  requestSerial += 1
  loading.value = false
  chartData.value = null
  selectInfo.value = null
  errorText.value = ''
}

function onPointClick(point) {
  selectInfo.value = { ...(selectInfo.value || {}), active_frame: point.frame_index }
  if (point.message_index != null) {
    emit('navigate-message', { message_index: point.message_index })
  }
}
</script>

<template>
  <div class="signal-timing">
    <SignalSelector
      :sessionId="sessionId"
      :meta="meta"
      :loading="loading"
      :prefill="prefill"
      @generate="onGenerate"
      @clear="onClear"
    />

    <section class="timing-body">
      <header class="chart-status">
        <div class="status-main">
          <span class="status-label">Current Selection</span>
          <strong>{{ selectInfo?.service_label || 'No service' }}</strong>
          <span v-if="selectInfo?.event_label" class="status-path">/ {{ selectInfo.event_label }}</span>
        </div>
        <div class="status-metrics">
          <span>{{ chartStats.fields }} fields</span>
          <span>{{ chartStats.points }} points</span>
          <span>{{ chartStats.transitions }} transitions</span>
          <span v-if="selectInfo?.active_frame">Frame {{ selectInfo.active_frame }}</span>
        </div>
      </header>

      <div class="signal-chart-area">
        <SignalChart
          :data="chartData"
          :selectInfo="selectInfo"
          :loading="loading"
          :errorText="errorText"
          :theme="theme"
          :timeRange="{
            start_time: selectInfo?.start_time,
            end_time: selectInfo?.end_time,
          }"
          @point-click="onPointClick"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
.signal-timing {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  min-width: 0;
}
.timing-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  box-shadow: var(--shadow-panel);
}
.chart-status {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 44px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-raised);
}
.status-main {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 7px;
  color: var(--text-primary);
}
.status-label {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}
.status-main strong,
.status-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.status-path {
  color: var(--text-secondary);
}
.status-metrics {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 7px;
}
.status-metrics span {
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-subtle);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 700;
}
.signal-chart-area {
  flex: 1;
  display: flex;
  min-height: 0;
  min-width: 0;
}
@media (max-width: 1000px) {
  .chart-status {
    align-items: flex-start;
    flex-direction: column;
  }
  .status-metrics {
    flex-wrap: wrap;
  }
}
</style>
