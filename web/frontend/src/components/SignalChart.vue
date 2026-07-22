<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, ScatterChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// Register only the chart primitives used on this page to keep the workbench bundle lean.
echarts.use([
  LineChart,
  ScatterChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = defineProps({
  data: { type: Object, default: null },
  selectInfo: { type: Object, default: null },
  loading: Boolean,
  errorText: { type: String, default: '' },
  theme: { type: String, default: 'light' },
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

watch([() => props.data, () => props.selectInfo, () => props.loading, () => props.errorText, () => props.theme], () => {
  nextTick(() => renderChart())
}, { deep: true })

function renderChart() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const ui = chartTheme(props.theme)

  if (props.loading) {
    chart.clear()
    chart.showLoading('default', {
      text: 'Loading signal data...',
      color: ui.accent,
      textColor: ui.textSecondary,
      maskColor: ui.loadingMask,
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
        itemStyle: { color, borderColor: ui.surface, borderWidth: 1.5 },
        emphasis: { scale: 1.5 },
        tooltip: { trigger: 'item' },
        encode: { x: 0, y: 1 },
      })
    }
  })

  const bounds = valueBounds(allVals)
  const seqBounds = valueBounds(allSeqs, 1)

  chart.setOption({
    backgroundColor: ui.surface,
    color: COLORS,
    title: {
      text: title,
      left: 14,
      top: 10,
      textStyle: { fontSize: 13, color: ui.textPrimary, fontWeight: 800 },
    },
    legend: {
      data: legendData,
      type: 'scroll',
      top: 12,
      right: 90,
      width: '48%',
      textStyle: { fontSize: 11, color: ui.textSecondary },
      itemWidth: 14,
      itemHeight: 9,
    },
    toolbox: {
      right: 12,
      top: 8,
      itemSize: 14,
      iconStyle: { borderColor: ui.textSecondary },
      emphasis: { iconStyle: { borderColor: ui.accent } },
      feature: {
        dataZoom: { yAxisIndex: 'none', title: { zoom: 'Zoom', back: 'Back' } },
        restore: { title: 'Restore' },
        saveAsImage: { title: 'Save' },
      },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: ui.tooltip,
      borderColor: ui.borderStrong,
      textStyle: { color: ui.textPrimary },
      axisPointer: { type: 'cross', label: { backgroundColor: ui.textSecondary } },
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
      axisLine: { lineStyle: { color: ui.borderStrong } },
      splitLine: { lineStyle: { color: ui.grid } },
      axisLabel: { color: ui.textSecondary, fontSize: 10 },
      nameTextStyle: { color: ui.textSecondary, fontSize: 11, fontWeight: 700 },
    },
    yAxis: {
      type: 'value',
      name: 'Value',
      nameGap: 34,
      min: bounds.min,
      max: bounds.max,
      scale: true,
      axisLine: { lineStyle: { color: ui.borderStrong } },
      splitLine: { lineStyle: { color: ui.grid } },
      axisLabel: { color: ui.textSecondary, fontSize: 10 },
      nameTextStyle: { color: ui.textSecondary, fontSize: 11, fontWeight: 700 },
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
        backgroundColor: ui.surfaceSubtle,
        borderColor: ui.border,
        fillerColor: ui.zoomFill,
        handleStyle: { color: ui.accent, borderColor: ui.accent },
        textStyle: { color: ui.textSecondary },
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
  const ui = chartTheme(props.theme)
  chart.hideLoading()
  chart.clear()
  chart.setOption({
    backgroundColor: ui.surface,
    title: {
      text,
      left: 'center',
      top: 'center',
      textStyle: { color: ui.textTertiary, fontSize: 14, fontWeight: 700 },
    },
  }, { notMerge: true })
}

// ECharts renders into canvas, so it consumes the same root theme through a
// small explicit palette instead of relying on CSS inheritance.
function chartTheme(theme) {
  if (theme === 'dark') {
    return {
      surface: '#1b1d1f', surfaceSubtle: '#24272a', tooltip: '#202225',
      textPrimary: '#f0f2f4', textSecondary: '#adb4bd', textTertiary: '#929aa4',
      border: '#35393e', borderStrong: '#4b5159', grid: '#303438', accent: '#78a5f5',
      zoomFill: 'rgba(120, 165, 245, .20)', loadingMask: 'rgba(27, 29, 31, .76)',
    }
  }
  return {
    surface: '#ffffff', surfaceSubtle: '#f7f8fa', tooltip: '#ffffff',
    textPrimary: '#171a1f', textSecondary: '#58616d', textTertiary: '#697482',
    border: '#d4d9e0', borderStrong: '#b8c0ca', grid: '#e5e8ec', accent: '#245dcc',
    zoomFill: 'rgba(36, 93, 204, .16)', loadingMask: 'rgba(255, 255, 255, .76)',
  }
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
  background: var(--surface);
}
.chart-canvas {
  width: 100%;
  height: 100%;
  min-height: 380px;
}
</style>
