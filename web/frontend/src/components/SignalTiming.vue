<script setup>
import { ref, watch } from 'vue'
import SignalSelector from './SignalSelector.vue'
import SignalChart from './SignalChart.vue'
import ParseTree from './ParseTree.vue'
import { fetchSignalMeta, fetchSignalData, fetchMessageDetail } from '../api'

const props = defineProps({
  sessionId: { type: String, required: true },
  prefill: { type: Object, default: null },
})

const meta = ref([])
const loading = ref(false)
const chartData = ref(null)
const selectInfo = ref(null)

// 加载级联选择器数据
watch(() => props.sessionId, (sid) => {
  if (sid) loadMeta(sid)
}, { immediate: true })

// 从诊断页跳转时自动生成曲线
watch(() => props.prefill, (pf) => {
  if (pf && meta.value.length) {
    // 找到 service 在 meta 中的位置
    selectInfo.value = pf
    onGenerate(pf)
  }
})

async function loadMeta(sid) {
  try {
    meta.value = await fetchSignalMeta(sid)
  } catch { meta.value = [] }
}

async function onGenerate(params) {
  loading.value = true
  selectInfo.value = params
  chartData.value = null
  detailMsg.value = null
  try {
    chartData.value = await fetchSignalData(
      props.sessionId, params.service_id, params.event_id, params.field_path
    )
  } catch { chartData.value = null }
  finally { loading.value = false }
}

async function onPointClick({ frame_index }) {
  if (!props.sessionId) return
  // frame_index is not the same as message index; we need to search
  // Actually the chart data has frame_index from the points
  // But the message detail API uses message index (not frame_index)
  // Let's just try to find a message with matching frame_index
  // We don't have direct access to messages here, so we use what we have
  // The chart click gives us frame_index but we need the message's index
  // For now, we can't easily map back; let's skip this handler
}

function onMsgSelect(msg) {
  // Could be used later
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
    />
    <div class="signal-workspace">
      <div class="signal-chart-area">
        <SignalChart
          :data="chartData"
          :selectInfo="selectInfo"
          @point-click="onPointClick"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.signal-timing {
  display: flex; flex-direction: column; height: 100%;
}
.signal-workspace {
  flex: 1; display: flex; overflow: hidden; min-height: 0;
}
.signal-chart-area {
  flex: 1; display: flex; min-height: 0;
  background: rgba(255,255,255,0.92); border: 1px solid #d8e0ea;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(31,45,61,0.08);
}
</style>
