<script setup>
import { ref, computed, watch, reactive, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  messages: Array, loading: Boolean, selectedIndex: Number, searchText: String,
})
const emit = defineEmits(['select', 'update:searchText'])

const currentPage = ref(1)
const tableWrap = ref(null)
const pageSize = 100

// ---- 列宽拖动 ----
const columnOrder = [
  'index', 'frame_index', 'timestamp', 'service_id', 'method_id',
  'msg_type', 'transport', 'payload_length', 'status',
]
const colWidths = reactive({
  index: 50,
  frame_index: 50,
  timestamp: 78,
  service_id: 92,
  method_id: 104,
  msg_type: 86,
  transport: 44,
  payload_length: 48,
  status: 68,
})
const flexColumnWeights = {
  timestamp: 1,
  service_id: 2,
  method_id: 2,
  msg_type: 1.5,
}
const minColWidths = computed(() => {
  const rows = props.messages || []
  return {
    // 紧凑列按当前数据最长文本计算，避免一位数抓包浪费宽度、多位数又被截断。
    index: compactColumnWidth('序号', rows, row => row.index, 46),
    frame_index: compactColumnWidth('帧号', rows, row => row.frame_index, 46),
    // 信息列只保证表头完整，内容过长时由单元格省略号和 title 承接。
    timestamp: 78,
    service_id: 92,
    method_id: 104,
    msg_type: 86,
    transport: compactColumnWidth('协议', rows, row => row.transport || '-', 44),
    payload_length: compactColumnWidth('长度', rows, row => row.payload_length, 48),
    // 状态单元格还包含标签自身的水平内边距和边框。
    status: compactColumnWidth('状态', rows, row => statusLabel(row.parse_status), 68, 32),
  }
})
const tableWidth = computed(() => (
  columnOrder.reduce((total, column) => total + colWidths[column], 0)
))
let resizeCol = null, resizeStartX = 0, resizeStartW = 0
let tableResizeObserver = null

watch(minColWidths, (widths) => {
  // 切换解析记录后重新按新数据计算，不继承上一组抓包的无效列宽。
  columnOrder.forEach((column) => { colWidths[column] = widths[column] })
  nextTick(measureTableViewport)
}, { immediate: true })

onMounted(() => {
  measureTableViewport()
  if (!tableWrap.value) return
  if (typeof ResizeObserver === 'undefined') {
    window.addEventListener('resize', measureTableViewport)
    return
  }
  tableResizeObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect?.width || 0
    resizeColumnsWithViewport(width)
  })
  tableResizeObserver.observe(tableWrap.value)
})

function measureTableViewport() {
  resizeColumnsWithViewport(tableWrap.value?.clientWidth || 0)
}

function resizeColumnsWithViewport(width) {
  const nextWidth = Math.floor(width)
  if (nextWidth <= 0 || resizeCol) return
  layoutColumns(nextWidth)
}

function layoutColumns(viewportWidth) {
  const widths = minColWidths.value
  const minimumTotal = columnOrder.reduce((total, column) => total + widths[column], 0)
  columnOrder.forEach((column) => { colWidths[column] = widths[column] })

  // 容器不足时保持最小总宽度，由 msg-table-wrap 提供底部横向滚动条。
  const extra = viewportWidth - minimumTotal
  if (extra <= 0) return

  const weightedColumns = Object.keys(flexColumnWeights)
  const totalWeight = weightedColumns.reduce(
    (total, column) => total + flexColumnWeights[column],
    0,
  )
  let distributed = 0
  weightedColumns.forEach((column, index) => {
    const addition = index === weightedColumns.length - 1
      ? extra - distributed
      : Math.floor(extra * flexColumnWeights[column] / totalWeight)
    colWidths[column] += addition
    distributed += addition
  })
}

function compactColumnWidth(header, rows, valueGetter, floor, horizontalChrome = 18) {
  let widest = estimateTextWidth(header)
  rows.forEach((row) => {
    widest = Math.max(widest, estimateTextWidth(valueGetter(row)))
  })
  return Math.max(floor, Math.ceil(widest + horizontalChrome))
}

function estimateTextWidth(value) {
  return [...String(value ?? '')].reduce((width, char) => (
    width + (/[^\x00-\xff]/.test(char) ? 12 : 7.3)
  ), 0)
}

function onResizeStart(col, e) {
  resizeCol = col; resizeStartX = e.clientX; resizeStartW = colWidths[col]
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
  document.body.classList.add('message-column-resizing')
  e.preventDefault()
}
function onResizeMove(e) {
  if (!resizeCol) return
  const delta = e.clientX - resizeStartX
  // 表格宽度由所有列之和决定，只修改当前列，不向相邻列借用空间。
  colWidths[resizeCol] = Math.max(minColWidths.value[resizeCol], resizeStartW + delta)
}
function onResizeEnd() {
  resizeCol = null
  document.body.classList.remove('message-column-resizing')
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
}
onUnmounted(() => {
  document.body.classList.remove('message-column-resizing')
  tableResizeObserver?.disconnect()
  window.removeEventListener('resize', measureTableViewport)
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
})

const filtered = computed(() => {
  if (!props.searchText) return props.messages || []
  const tokens = props.searchText
    .toLowerCase()
    .split(/\s+/)
    .map(v => v.trim())
    .filter(Boolean)

  return (props.messages || []).filter(m =>
    tokens.every(q => [
      String(m.index),
      String(m.frame_index),
      String(m.timestamp_iso),
      String(formatTimestamp(m.timestamp_epoch)),
      String(m.payload_length),
      String(m.service_id),
      String(m.service_name),
      String(m.method_id),
      String(m.method_name),
      String(m.message_type),
      String(m.message_type_name),
      String(m.message_kind),
      String(m.parse_status),
      String(m.transport || ''),
    ].some(field => field.toLowerCase().includes(q)))
  )
})

const paged = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filtered.value.slice(start, start + pageSize)
})

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))

watch(() => props.messages, () => { currentPage.value = 1 })
watch(filtered, () => { currentPage.value = 1 })
watch(currentPage, () => {
  nextTick(() => {
    tableWrap.value?.scrollTo({ top: 0, behavior: 'auto' })
  })
})

function goPage(v) {
  const n = parseInt(v, 10)
  if (n >= 1 && n <= totalPages.value) currentPage.value = n
}

function clearSearch() {
  emit('update:searchText', '')
}

function fmtId(hex, name) {
  if (name) return `${hex} (${name})`
  return hex
}

function fmtMsgType(m) {
  if (m.message_type_name) return `${m.message_type} ${m.message_type_name}`
  return m.message_type || '-'
}

function formatTimestamp(epoch) {
  const n = Number(epoch)
  if (!Number.isFinite(n) || n <= 0) return '-'
  const d = new Date(n * 1000)
  const pad = (v, len = 2) => String(v).padStart(len, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
}

function statusLabel(s) {
  if (s === 'ok') return '已解析'
  if (s === 'sd') return 'SD'
  return '未解析'
}
function statusClass(s) {
  if (s === 'ok') return 'tag-ok'
  if (s === 'sd') return 'tag-sd'
  return 'tag-fail'
}

function resolvedCount(messages) {
  return (messages || []).filter(m => m.parse_status !== 'unresolved').length
}

async function revealMessage(messageIndex) {
  // AI 证据跳转时先定位过滤结果中的页码，再把目标行滚动到可视区域。
  const index = filtered.value.findIndex(item => Number(item.index) === Number(messageIndex))
  if (index < 0) return false
  currentPage.value = Math.floor(index / pageSize) + 1
  await nextTick()
  const row = tableWrap.value?.querySelector(`[data-message-index="${Number(messageIndex)}"]`)
  row?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  return true
}

defineExpose({ revealMessage })
</script>

<template>
  <div class="msg-panel">
    <div class="msg-header">
      <div class="msg-title-block">
        <span class="msg-title">消息列表 ({{ filtered.length }} 条)
        <template v-if="!loading && props.messages?.length">
          · 已解析 {{ resolvedCount(props.messages) }}
        </template>
        </span>
        <span class="msg-subtitle">支持多关键字组合搜索，如 0x1234 response ok</span>
      </div>
      <div class="search-box">
        <input class="search-input" placeholder="搜索序号/帧号/长度/ID/类型/状态(sd/ok)/协议..."
               :value="searchText"
               @input="emit('update:searchText', $event.target.value)">
        <button v-if="searchText" class="search-clear" @click="clearSearch">清空</button>
      </div>
    </div>
    <div class="msg-table-wrap" ref="tableWrap">
      <table
        class="msg-table"
        :style="{ width: tableWidth + 'px', minWidth: tableWidth + 'px' }"
      >
        <colgroup>
          <col
            v-for="column in columnOrder"
            :key="column"
            :style="{ width: colWidths[column] + 'px' }"
          >
        </colgroup>
        <thead>
          <tr>
            <th>序号<span class="col-resize" @mousedown="onResizeStart('index', $event)"></span></th>
            <th>帧号<span class="col-resize" @mousedown="onResizeStart('frame_index', $event)"></span></th>
            <th>Time<span class="col-resize" @mousedown="onResizeStart('timestamp', $event)"></span></th>
            <th>Service ID<span class="col-resize" @mousedown="onResizeStart('service_id', $event)"></span></th>
            <th>Method/Event<span class="col-resize" @mousedown="onResizeStart('method_id', $event)"></span></th>
            <th>Msg Type<span class="col-resize" @mousedown="onResizeStart('msg_type', $event)"></span></th>
            <th>协议<span class="col-resize" @mousedown="onResizeStart('transport', $event)"></span></th>
            <th>长度<span class="col-resize" @mousedown="onResizeStart('payload_length', $event)"></span></th>
            <th>状态<span class="col-resize" @mousedown="onResizeStart('status', $event)"></span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="9" class="empty">解析中...</td></tr>
          <tr v-else-if="!paged.length"><td colspan="9" class="empty">无匹配结果</td></tr>
          <tr v-for="m in paged" :key="m.index"
              :data-message-index="m.index"
              :class="{ selected: m.index === selectedIndex }"
              class="msg-row"
              @click="emit('select', m)">
            <td class="mono">{{ m.index }}</td>
            <td class="mono">{{ m.frame_index }}</td>
            <td class="mono" :title="m.timestamp_iso || ''">{{ formatTimestamp(m.timestamp_epoch) }}</td>
            <td class="mono" :title="fmtId(m.service_id, m.service_name)">{{ fmtId(m.service_id, m.service_name) }}</td>
            <td class="mono" :title="fmtId(m.method_id, m.method_name)">{{ fmtId(m.method_id, m.method_name) }}</td>
            <td class="mono" :title="fmtMsgType(m)">{{ fmtMsgType(m) }}</td>
            <td class="mono" :title="m.transport || '-'">{{ m.transport || '-' }}</td>
            <td class="mono" style="text-align:right">{{ m.payload_length }}</td>
            <td>
              <span class="tag" :class="statusClass(m.parse_status)">
                {{ statusLabel(m.parse_status) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="msg-footer" v-if="filtered.length > pageSize">
      <button :disabled="currentPage <= 1" @click="currentPage--">上一页</button>
      <input class="page-num" :value="currentPage" @change="goPage($event.target.value)" style="width:40px;text-align:center">
      <span>/ {{ totalPages }}</span>
      <button :disabled="currentPage >= totalPages" @click="currentPage++">下一页</button>
    </div>
  </div>
</template>

<style>
.msg-panel { display: flex; flex-direction: column; height: 100%; background: var(--surface); color: var(--text-primary); }
.msg-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 11px 13px;
  background: var(--surface-raised);
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  flex-shrink: 0;
  gap: 12px;
}
.msg-title-block { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.msg-title { font-weight: 900; color: var(--text-primary); }
.msg-subtitle { color: var(--text-secondary); font-size: 12px; }
.search-box { display: flex; align-items: center; gap: 8px; }
.search-clear {
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--radius-control);
  min-height: 31px;
  padding: 0 10px;
  font-size: 12px;
  cursor: pointer;
  color: var(--text-secondary);
  font-weight: 800;
}
.search-clear:hover { border-color: var(--accent-border); color: var(--accent); background: var(--accent-soft); }
.search-input {
  width: 300px;
  min-height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  font-size: 12px;
  outline: none;
  background: var(--surface);
  color: var(--text-primary);
}
.search-input::placeholder { color: var(--text-tertiary); }
.search-input:focus { border-color: var(--accent); box-shadow: var(--focus-ring); }
.msg-table-wrap { flex: 1; overflow: auto; background: var(--surface); }
.msg-table { border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.message-column-resizing,
.message-column-resizing * {
  cursor: col-resize !important;
  user-select: none !important;
}
.col-resize {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  background: transparent;
}
.col-resize:hover { background: var(--accent); }
.msg-table th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface-muted);
  padding: 8px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border-strong);
  border-right: 1px solid var(--border);
  font-weight: 900;
  color: var(--text-primary);
}
.msg-table td {
  padding: 7px 8px;
  border-bottom: 1px solid var(--border);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
}
.msg-row { cursor: pointer; }
.msg-row:nth-child(even) { background: var(--surface-subtle); }
.msg-row:hover { background: var(--surface-hover); }
.msg-row.selected { background: var(--surface-selected); box-shadow: inset 3px 0 0 var(--accent); }
.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.empty { text-align: center; color: var(--text-secondary); padding: 24px; }
.tag {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 0 7px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 900;
}
.tag-ok { background: var(--success-soft); color: var(--success); border: 1px solid var(--success-border); }
.tag-sd { background: var(--warning-soft); color: var(--warning); border: 1px solid var(--warning-border); }
.tag-fail { background: var(--danger-soft); color: var(--danger); border: 1px solid var(--danger-border); }
.msg-footer {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 7px;
  padding: 9px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  flex-shrink: 0;
  background: var(--surface-subtle);
}
.msg-footer button {
  min-height: 28px;
  padding: 0 12px;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  font-weight: 800;
}
.msg-footer button:hover:not(:disabled) { border-color: var(--accent-border); color: var(--accent); }
.msg-footer button:disabled { color: var(--text-tertiary); cursor: not-allowed; }
.page-num { border: 1px solid var(--border); border-radius: var(--radius-control); padding: 4px; font-size: 12px; background: var(--surface); color: var(--text-primary); }
@media (max-width: 900px) {
  .msg-header { flex-direction: column; align-items: stretch; }
  .search-box { width: 100%; }
  .search-input { width: 100%; }
}
</style>
