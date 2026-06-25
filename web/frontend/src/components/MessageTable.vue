<script setup>
import { ref, computed, watch, reactive, onUnmounted } from 'vue'

const props = defineProps({
  messages: Array, loading: Boolean, selectedIndex: Number, searchText: String,
})
const emit = defineEmits(['select', 'update:searchText'])

const currentPage = ref(1)
const pageSize = 100

// ---- 列宽拖动 ----
const colWidths = reactive({
  index: 45, frame_index: 45, service_id: 140, method_id: 140,
  msg_type: 70, transport: 52, payload_length: 45, status: 55,
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
      String(m.payload_length),
      String(m.service_id),
      String(m.service_name),
      String(m.method_id),
      String(m.method_name),
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
    <div class="msg-table-wrap">
      <table class="msg-table">
        <thead>
          <tr>
            <th :style="{ width: colWidths.index + 'px' }">序号<span class="col-resize" @mousedown="onResizeStart('index', $event)"></span></th>
            <th :style="{ width: colWidths.frame_index + 'px' }">帧号<span class="col-resize" @mousedown="onResizeStart('frame_index', $event)"></span></th>
            <th :style="{ width: colWidths.service_id + 'px' }">Service ID<span class="col-resize" @mousedown="onResizeStart('service_id', $event)"></span></th>
            <th :style="{ width: colWidths.method_id + 'px' }">Method/Event<span class="col-resize" @mousedown="onResizeStart('method_id', $event)"></span></th>
            <th :style="{ width: colWidths.msg_type + 'px' }">msg_type<span class="col-resize" @mousedown="onResizeStart('msg_type', $event)"></span></th>
            <th :style="{ width: colWidths.transport + 'px' }">协议<span class="col-resize" @mousedown="onResizeStart('transport', $event)"></span></th>
            <th :style="{ width: colWidths.payload_length + 'px' }">长度<span class="col-resize" @mousedown="onResizeStart('payload_length', $event)"></span></th>
            <th :style="{ width: colWidths.status + 'px' }">状态<span class="col-resize" @mousedown="onResizeStart('status', $event)"></span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="8" class="empty">解析中...</td></tr>
          <tr v-else-if="!paged.length"><td colspan="8" class="empty">无匹配结果</td></tr>
          <tr v-for="m in paged" :key="m.index"
              :class="{ selected: m.index === selectedIndex }"
              class="msg-row"
              @click="emit('select', m)">
            <td class="mono">{{ m.index }}</td>
            <td class="mono">{{ m.frame_index }}</td>
            <td class="mono">{{ fmtId(m.service_id, m.service_name) }}</td>
            <td class="mono">{{ fmtId(m.method_id, m.method_name) }}</td>
            <td class="mono">{{ m.message_kind }}</td>
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
.msg-panel { display: flex; flex-direction: column; height: 100%; }
.msg-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 12px; background: linear-gradient(180deg, #f9fbfd, #f1f5f9);
  border-bottom: 1px solid #e5ebf2; font-size: 13px; flex-shrink: 0; gap: 12px;
}
.msg-title-block { display: flex; flex-direction: column; gap: 4px; }
.msg-title { font-weight: 700; color: #303133; }
.msg-subtitle { color: #909399; font-size: 12px; }
.search-box { display: flex; align-items: center; gap: 8px; }
.search-clear {
  border: 1px solid #d0d8e4; background: #fff; border-radius: 7px; padding: 5px 10px;
  font-size: 12px; cursor: pointer; color: #606266;
}
.search-input {
  width: 280px; padding: 7px 10px; border: 1px solid #d4dbe6; border-radius: 7px;
  font-size: 12px; outline: none; background: #fff;
}
.search-input:focus { border-color: #409eff; box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.12); }
.msg-table-wrap { flex: 1; overflow: auto; }
.msg-table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.col-resize {
  position: absolute; right: 0; top: 0; bottom: 0; width: 6px; cursor: col-resize;
  background: transparent; transition: background .15s;
}
.col-resize:hover { background: #409eff; }
.msg-table th { position: relative; }
.msg-table th {
  position: sticky; top: 0; background: #f7fafd; padding: 7px 8px;
  text-align: left; border-bottom: 1px solid #e5ebf2; font-weight: 700; z-index: 1;
}
.msg-table td { padding: 6px 8px; border-bottom: 1px solid #f1f4f8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg-row { cursor: pointer; }
.msg-row:nth-child(even) { background: #fcfdff; }
.msg-row:hover { background: #f0f7ff; }
.msg-row.selected { background: #e6f2ff; box-shadow: inset 3px 0 0 #409eff; }
.mono { font-family: 'Consolas','Courier New',monospace; }
.empty { text-align: center; color: #999; padding: 20px; }
.tag { font-size: 11px; padding: 2px 7px; border-radius: 999px; }
.tag-ok { background: #e1f3d8; color: #67c23a; }
.tag-sd { background: #fef6ed; color: #e6a23c; }
.tag-fail { background: #fef0f0; color: #f56c6c; }
.msg-footer {
  display: flex; justify-content: center; align-items: center; gap: 6px;
  padding: 8px; border-top: 1px solid #e5ebf2; font-size: 12px; flex-shrink: 0; background: #fafcff;
}
.msg-footer button { padding: 4px 12px; cursor: pointer; border: 1px solid #d0d8e4; background: #fff; border-radius: 6px; }
.page-num { border: 1px solid #dcdfe6; border-radius: 2px; padding: 2px 4px; font-size: 12px; }
@media (max-width: 900px) {
  .msg-header { flex-direction: column; align-items: stretch; }
  .search-box { width: 100%; }
  .search-input { width: 100%; }
}
</style>
