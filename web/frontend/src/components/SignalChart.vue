<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: { type: Object, default: null },
  selectInfo: { type: Object, default: null },
})
const emit = defineEmits(['point-click'])

const chartEl = ref(null)
let chart = null
let resizeObserver = null

onMounted(() => {
  resizeObserver = new ResizeObserver(() => chart?.resize())
  if (chartEl.value) resizeObserver.observe(chartEl.value)
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  chart?.dispose()
})

watch([() => props.data, () => props.selectInfo], () => {
  nextTick(() => renderChart())
}, { deep: true })

function renderChart() {
  if (!chartEl.value) return

  if (!chart) {
    chart = echarts.init(chartEl.value)
  }

  const data = props.data
  const sel = props.selectInfo || {}
  if (!data || !data.points || !data.points.length) {
    chart.clear()
    chart.setOption({
      title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
    })
    return
  }

  const xs = data.points.map(p => p.seq)
  const ys = data.points.map(p => p.value)
  const transYs = data.transitions?.map(t => t.new_value) || []

  const allVals = [...ys, ...transYs]
  const isInteger = allVals.length > 0 && allVals.every(v => Number.isInteger(v))
  const yMin = allVals.length > 0 ? Math.min(...allVals) : 0
  const yMax = allVals.length > 0 ? Math.max(...allVals) : 0
  const yRange = yMax - yMin

  // 计算 Y 轴范围：留 10% 上下边距，常量值至少 ±0.5（整数）或 ±1%（浮点）
  const yPad = yRange > 0
    ? yRange * 0.1
    : (isInteger ? 1 : Math.max(Math.abs(yMin) * 0.05, 0.1))
  const yAxisMin = yMin - yPad
  const yAxisMax = yMax + yPad

  const fieldName = sel.field_path || 'value'
  const title = sel.service_label && sel.event_label
    ? `${sel.service_label} / ${sel.event_label} · ${fieldName}`
    : fieldName

  chart.setOption({
    title: {
      text: title,
      left: 12, top: 8,
      textStyle: { fontSize: 13, color: '#303133' },
    },
    tooltip: {
      trigger: 'item',
      formatter(p) {
        if (p.seriesName === '跳变点') {
          const idx = p.dataIndex
          const t = data.transitions[idx]
          if (t) {
            return `<b>跳变点</b><br/>Frame: ${t.frame_index}<br/>${t.old_value} → <b>${t.new_value}</b><br/>Seq: ${t.seq}`
          }
        }
        return `<b>${fieldName}</b><br/>Frame: ${data.points[p.dataIndex]?.frame_index}<br/>值: <b>${p.value}</b><br/>Seq: ${p.name}`
      },
    },
    grid: { left: 52, right: 20, top: 52, bottom: 36 },
    xAxis: {
      type: 'category',
      data: xs,
      name: '序号',
      nameLocation: 'center',
      nameGap: 28,
      nameTextStyle: { fontSize: 11, color: '#909399' },
      axisLabel: { fontSize: 10, rotate: xs.length > 30 ? 45 : 0 },
    },
    yAxis: {
      type: 'value',
      name: fieldName,
      min: yAxisMin,
      max: yAxisMax,
      nameTextStyle: { fontSize: 11, color: '#909399' },
      axisLabel: {
        fontSize: 10,
        formatter: isInteger
          ? (v) => Number.isInteger(v) ? v : v.toFixed(0)
          : (v) => v.toFixed(2),
      },
    },
    // 仅 X 轴缩放（滑块 + 鼠标滚轮），不缩放 Y 轴（避免 Y 轴跟丢）
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseMove: true },
      { type: 'slider', xAxisIndex: 0, bottom: 4, height: 18, showDetail: false },
    ],
    series: [
      {
        name: fieldName,
        type: 'line',
        data: ys,
        smooth: false,
        symbol: 'circle',
        symbolSize: xs.length > 100 ? 2 : 5,
        lineStyle: { color: '#409eff', width: 1.5 },
        itemStyle: { color: '#409eff' },
        emphasis: { itemStyle: { borderWidth: 2, borderColor: '#fff' } },
      },
      {
        name: '跳变点',
        type: 'scatter',
        data: transYs,
        symbol: 'circle',
        symbolSize: 10,
        itemStyle: { color: '#f56c6c', borderColor: '#fff', borderWidth: 1.5 },
        emphasis: { scale: 1.4 },
        tooltip: { trigger: 'item' },
      },
    ],
  })

  chart.off('click')
  chart.on('click', (params) => {
    if (params.componentType === 'series') {
      const pt = data.points[params.dataIndex]
      if (pt) {
        emit('point-click', { frame_index: pt.frame_index })
      }
    }
  })
}
</script>

<template>
  <div class="chart-wrap">
    <div ref="chartEl" class="chart-canvas"></div>
  </div>
</template>

<style scoped>
.chart-wrap { flex: 1; display: flex; min-height: 0; width: 100%; }
.chart-canvas { width: 100%; height: 100%; min-height: 300px; }
</style>
