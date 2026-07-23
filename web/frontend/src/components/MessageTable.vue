<script setup>
import { ref, computed, watch, reactive, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  messages: Array, loading: Boolean, selectedIndex: Number, searchText: String,
})
const emit = defineEmits(['select', 'update:searchText'])

const currentPage = ref(1)
const tableWrap = ref(null)
const pageSize = 100

// ---- 列宽拖动 ----
const colWidths = reactive({
  index: 45, frame_index: 45, timestamp: 108, service_id: 140, method_id: 140,
  msg_type: 110, transport: 52, payload_length: 45, status: 55,
})
let resizeCol = null, resizeStartX = 0, resizeStartW = 0

function onResizeStart(col, e) {
  resizeCol = col; resizeStartX = e.clientX; resizeStartW = colWidths[col]
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
  e.preventDefault()
}
function onResizeMove(e) {
  if (!resizeCol) return
  const delta = e.clientX - resizeStartX
  colWidths[resizeCol] = Math.max(30, resizeStartW + delta)
}
function onResizeEnd() {
  resizeCol = null
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
}
onUnmounted(() => {
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
      <table class="msg-table">
        <thead>
          <tr>
            <th :style="{ width: colWidths.index + 'px' }">序号<span class="col-resize" @mousedown="onResizeStart('index', $event)"></span></th>
            <th :style="{ width: colWidths.frame_index + 'px' }">帧号<span class="col-resize" @mousedown="onResizeStart('frame_index', $event)"></span></th>
            <th :style="{ width: colWidths.timestamp + 'px' }">Time<span class="col-resize" @mousedown="onResizeStart('timestamp', $event)"></span></th>
            <th :style="{ width: colWidths.service_id + 'px' }">Service ID<span class="col-resize" @mousedown="onResizeStart('service_id', $event)"></span></th>
            <th :style="{ width: colWidths.method_id + 'px' }">Method/Event<span class="col-resize" @mousedown="onResizeStart('method_id', $event)"></span></th>
            <th :style="{ width: colWidths.msg_type + 'px' }">Msg Type<span class="col-resize" @mousedown="onResizeStart('msg_type', $event)"></span></th>
            <th :style="{ width: colWidths.transport + 'px' }">协议<span class="col-resize" @mousedown="onResizeStart('transport', $event)"></span></th>
            <th :style="{ width: colWidths.payload_length + 'px' }">长度<span class="col-resize" @mousedown="onResizeStart('payload_length', $event)"></span></th>
            <th :style="{ width: colWidths.status + 'px' }">状态<span class="col-resize" @mousedown="onResizeStart('status', $event)"></span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="9" class="empty">解析中...</td></tr>
          <tr v-else-if="!paged.length"><td colspan="9" class="empty">无匹配结果</td></tr>
          <tr v-for="m in paged" :key="m.index"
              :class="{ selected: m.index === selectedIndex }"
              class="msg-row"
              @click="emit('select', m)">
            <td class="mono">{{ m.index }}</td>
            <td class="mono">{{ m.frame_index }}</td>
            <td class="mono" :title="m.timestamp_iso || ''">{{ formatTimestamp(m.timestamp_epoch) }}</td>
            <td class="mono">{{ fmtId(m.service_id, m.service_name) }}</td>
            <td class="mono">{{ fmtId(m.method_id, m.method_name) }}</td>
            <td class="mono">{{ fmtMsgType(m) }}</td>
            <td class="mono">{{ m.transport || '-' }}</td>
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
.msg-table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
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
