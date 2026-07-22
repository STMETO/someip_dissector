<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: { type: Object, default: null },
  selectInfo: { type: Object, default: null },
  loading: Boolean,
  errorText: { type: String, default: '' },
})
const emit = defineEmits(['point-click'])

const COLORS = ['#0284c7', '#16a34a', '#ea580c', '#dc2626', '#7c3aed', '#0891b2', '#be123c', '#4b5563']

const chartEl = ref(null)
let chart = null
let resizeObserver = null

onMounted(() => {
  resizeObserver = new ResizeObserver(() => chart?.resize())
  if (chartEl.value) resizeObserver.observe(chartEl.value)
  renderChart()
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})

watch([() => props.data, () => props.selectInfo, () => props.loading, () => props.errorText], () => {
  nextTick(() => renderChart())
}, { deep: true })

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)

  if (props.loading) {
    chart.clear()
    chart.showLoading('default', {
      text: 'Loading signal data...',
      color: '#0284c7',
      textColor: '#64748b',
      maskColor: 'rgba(248,250,252,.72)',
    })
    return
  }

  chart.hideLoading()

  if (props.errorText) {
    renderEmpty(props.errorText)
    return
  }

  const data = props.data
  const fields = (data?.fields || []).map((field) => {
    const points = (field.points || [])
      .map(point => ({ ...point, y: normalizeValue(point.value) }))
      .filter(point => Number.isFinite(point.y))
    return { ...field, points }
  })
  const visibleFields = fields.filter(field => field.points.length)

  if (!visibleFields.length) {
    renderEmpty('No signal data')
    return
  }

  const title = props.selectInfo?.service_label && props.selectInfo?.event_label
    ? `${props.selectInfo.service_label} / ${props.selectInfo.event_label}`
    : 'Signal Timing'

  const legendData = []
  const series = []
  const allVals = []
  const allSeqs = []

  visibleFields.forEach((field, index) => {
    const color = COLORS[index % COLORS.length]
    const points = field.points
    const lineData = points.map(point => {
      allVals.push(point.y)
      allSeqs.push(point.seq)
      return [point.seq, point.y, point]
    })

    legendData.push(field.field_path)
    series.push({
      name: field.field_path,
      type: 'line',
      data: lineData,
      smooth: false,
      showSymbol: points.length <= 220,
      symbol: 'circle',
      symbolSize: points.length > 100 ? 3 : 5,
      sampling: points.length > 800 ? 'lttb' : undefined,
      emphasis: { focus: 'series' },
      lineStyle: { color, width: 1.8 },
      itemStyle: { color },
      encode: { x: 0, y: 1 },
    })

    const transitions = (field.transitions || [])
      .map(item => ({ ...item, y: normalizeValue(item.new_value) }))
      .filter(item => Number.isFinite(item.y))

    if (transitions.length) {
      series.push({
        name: `${field.field_path} transitions`,
        type: 'scatter',
        data: transitions.map(item => [item.seq, item.y, item]),
        symbol: 'diamond',
        symbolSize: 10,
        itemStyle: { color, borderColor: '#fff', borderWidth: 1.5 },
        emphasis: { scale: 1.5 },
        tooltip: { trigger: 'item' },
        encode: { x: 0, y: 1 },
      })
    }
  })

  const bounds = valueBounds(allVals)
  const seqBounds = valueBounds(allSeqs, 1)

  chart.setOption({
    backgroundColor: '#f8fafc',
    color: COLORS,
    title: {
      text: title,
      left: 14,
      top: 10,
      textStyle: { fontSize: 13, color: '#172033', fontWeight: 800 },
    },
    legend: {
      data: legendData,
      type: 'scroll',
      top: 12,
      right: 90,
      width: '48%',
      textStyle: { fontSize: 11, color: '#475569' },
      itemWidth: 14,
      itemHeight: 9,
    },
    toolbox: {
      right: 12,
      top: 8,
      itemSize: 14,
      feature: {
        dataZoom: { yAxisIndex: 'none', title: { zoom: 'Zoom', back: 'Back' } },
        restore: { title: 'Restore' },
        saveAsImage: { title: 'Save' },
      },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: '#475569' } },
      confine: true,
      formatter(params) {
        const items = Array.isArray(params) ? params : [params]
        return items.map(formatTooltipItem).filter(Boolean).join('<br/><br/>')
      },
    },
    grid: { left: 58, right: 24, top: 68, bottom: 58, containLabel: true },
    xAxis: {
      type: 'value',
      name: 'Seq',
      nameLocation: 'center',
      nameGap: 30,
      min: seqBounds.min,
      max: seqBounds.max,
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b', fontSize: 10 },
      nameTextStyle: { color: '#64748b', fontSize: 11, fontWeight: 700 },
    },
    yAxis: {
      type: 'value',
      name: 'Value',
      nameGap: 34,
      min: bounds.min,
      max: bounds.max,
      scale: true,
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#64748b', fontSize: 10 },
      nameTextStyle: { color: '#64748b', fontSize: 11, fontWeight: 700 },
    },
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'none',
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        bottom: 18,
        height: 22,
        filterMode: 'none',
        brushSelect: true,
        showDataShadow: true,
      },
    ],
    series,
  }, { notMerge: true })

  chart.off('click')
  chart.on('click', (params) => {
    if (params.componentType !== 'series' || String(params.seriesName).includes('transitions')) return
    const point = params.data?.[2]
    if (point) emit('point-click', { frame_index: point.frame_index, seq: point.seq })
  })
}

function renderEmpty(text) {
  chart.hideLoading()
  chart.clear()
  chart.setOption({
    backgroundColor: '#f8fafc',
    title: {
      text,
      left: 'center',
      top: 'center',
      textStyle: { color: '#94a3b8', fontSize: 14, fontWeight: 700 },
    },
  }, { notMerge: true })
}

function normalizeValue(value) {
  if (typeof value === 'boolean') return value ? 1 : 0
  const n = Number(value)
  return Number.isFinite(n) ? n : NaN
}

function valueBounds(values, minPad = 0) {
  const nums = values.filter(Number.isFinite)
  if (!nums.length) return { min: 0, max: 1 }
  const min = Math.min(...nums)
  const max = Math.max(...nums)
  const range = max - min
  const pad = Math.max(minPad, range > 0 ? range * 0.08 : Math.max(Math.abs(min) * 0.08, 1))
  return { min: min - pad, max: max + pad }
}

function formatTooltipItem(item) {
  const payload = item.data?.[2]
  if (!payload) return ''

  if (String(item.seriesName).includes('transitions')) {
    return [
      `<b>${escapeHtml(item.seriesName)}</b>`,
      `Seq: ${payload.seq}`,
      `Value: <b>${escapeHtml(payload.old_value)} -> ${escapeHtml(payload.new_value)}</b>`,
    ].join('<br/>')
  }

  return [
    `<b>${escapeHtml(item.seriesName)}</b>`,
    `Time: ${formatTimestamp(payload.timestamp_epoch)}`,
    `Frame: ${payload.frame_index ?? '-'}`,
    `Seq: ${payload.seq ?? item.value?.[0] ?? '-'}`,
    `Value: <b>${escapeHtml(payload.value)}</b>`,
  ].join('<br/>')
}

function formatTimestamp(epoch) {
  const n = Number(epoch)
  if (!Number.isFinite(n) || n <= 0) return '-'
  const d = new Date(n * 1000)
  const pad = (v, len = 2) => String(v).padStart(len, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

function escapeHtml(value) {
  return String(value ?? '-')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}
</script>

<template>
  <div class="chart-wrap">
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<style scoped>
.chart-wrap {
  flex: 1;
  display: flex;
  min-height: 0;
  width: 100%;
  background: #f8fafc;
}
.chart-canvas {
  width: 100%;
  height: 100%;
  min-height: 380px;
}
</style>
