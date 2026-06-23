<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: { type: Object, default: null },
  selectInfo: { type: Object, default: null },
})
const emit = defineEmits(['point-click'])

const COLORS = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#b37feb', '#36cfc9', '#ff7c43']

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
  if (!chart) chart = echarts.init(chartEl.value)

  const data = props.data
  if (!data || !data.fields || !data.fields.length || !data.fields.some(f => f.points?.length)) {
    chart.clear()
    chart.setOption({
      title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
    })
    return
  }

  const sel = props.selectInfo || {}
  const title = sel.service_label && sel.event_label
    ? `${sel.service_label} / ${sel.event_label}`
    : '信号时序'

  const series = []
  const legendData = []

  // 收集全局 value 范围
  let allVals = []
  data.fields.forEach((f, fi) => {
    const name = f.field_path
    const color = COLORS[fi % COLORS.length]
    const ys = (f.points || []).map(p => p.value)
    allVals = allVals.concat(ys)
    const xs = (f.points || []).map(p => p.seq)

    legendData.push(name)
    series.push({
      name,
      type: 'line',
      data: ys,
      smooth: false,
      symbol: 'circle',
      symbolSize: (f.points || []).length > 100 ? 2 : 5,
      lineStyle: { color, width: 1.5 },
      itemStyle: { color },
    })

    // 跳变点
    if (f.transitions && f.transitions.length) {
      const tXs = f.transitions.map(t => t.seq)
      const tYs = f.transitions.map(t => t.new_value)
      series.push({
        name: `${name} 跳变`,
        type: 'scatter',
        data: tYs,
        symbol: 'circle',
        symbolSize: 10,
        itemStyle: { color, borderColor: '#fff', borderWidth: 1.5 },
        emphasis: { scale: 1.4 },
      })
    }
  })

  const yMin = Math.min(...allVals)
  const yMax = Math.max(...allVals)
  const yRange = yMax - yMin
  const isInteger = allVals.every(v => Number.isInteger(v))
  const yPad = yRange > 0 ? yRange * 0.1 : (isInteger ? 1 : Math.max(Math.abs(yMin) * 0.05, 0.1))

  chart.setOption({
    title: { text: title, left: 12, top: 8, textStyle: { fontSize: 13, color: '#303133' } },
    legend: {
      data: legendData, type: 'scroll', top: 6, right: 12,
      textStyle: { fontSize: 11 }, itemWidth: 14, itemHeight: 10,
    },
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        if (!Array.isArray(params)) params = [params]
        return params.filter(p => !p.seriesName.includes('跳变')).map(p =>
          `<b>${p.seriesName}</b><br/>Seq: ${p.name}<br/>值: <b>${p.value}</b>`
        ).join('<br/>')
      },
    },
    grid: { left: 52, right: 20, top: 60, bottom: 36 },
    xAxis: {
      type: 'category', name: '序号', nameLocation: 'center', nameGap: 28,
      nameTextStyle: { fontSize: 11, color: '#909399' },
      axisLabel: { fontSize: 10 },
    },
    yAxis: {
      type: 'value', min: yMin - yPad, max: yMax + yPad,
      axisLabel: { fontSize: 10, formatter: isInteger ? '{value}' : v => v.toFixed(2) },
    },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: true, moveOnMouseMove: true },
      { type: 'slider', xAxisIndex: 0, bottom: 4, height: 18, showDetail: false },
    ],
    series,
  })

  chart.off('click')
  chart.on('click', (params) => {
    if (params.componentType === 'series' && !params.seriesName.includes('跳变')) {
      const fi = legendData.indexOf(params.seriesName)
      if (fi >= 0 && data.fields[fi]) {
        const pt = data.fields[fi].points?.[params.dataIndex]
        if (pt) emit('point-click', { frame_index: pt.frame_index })
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
