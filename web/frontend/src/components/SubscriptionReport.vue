<script setup>
import { ref, computed, watch, reactive, onUnmounted } from 'vue'
import { fetchSubscriptionReport } from '../api'

// ---- 列宽拖动 ----
const colWidths = reactive({
  svc: 170, eg: 80, evt: 200, offer: 50, sub: 62, notif: 50, issue: 0,
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
  colWidths[resizeCol] = Math.max(30, resizeStartW + (e.clientX - resizeStartX))
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

const props = defineProps({
  sessionId: { type: String, required: true },
})
const emit = defineEmits(['jump-signal'])

const loading = ref(false)
const report = ref(null)

watch(() => props.sessionId, (sid) => {
  if (sid) loadReport()
}, { immediate: true })

async function loadReport() {
  loading.value = true
  report.value = null
  try {
    report.value = await fetchSubscriptionReport(props.sessionId)
  } catch { report.value = null }
  finally { loading.value = false }
}

function fmtSvc(row) {
  const h = row.service_id_hex
  const n = row.service_name
  return n ? `${h} (${n})` : h
}

function fmtEg(row) {
  // EG ID（Group名）
  if (row.eventgroup_id == null) return '—'
  const h = '0x' + row.eventgroup_id.toString(16).toUpperCase().padStart(4, '0')
  const gn = row.eventgroup_name
  return gn ? `${h}（${gn}）` : h
}

function fmtEvtGroup(row) {
  // event_ID（事件名）
  if (row.eventgroup_id == null) return ''
  const notifId = row.eventgroup_id | 0x8000
  const nh = '0x' + notifId.toString(16).toUpperCase().padStart(4, '0')
  const en = row.event_name
  return en ? `${nh}（${en}）` : nh
}

// 展开为表格行
const rows = computed(() => {
  if (!report.value) return []
  const result = []
  for (const srv of report.value.services) {
    // 服务级问题行
    if (srv.issues.length > 0) {
      for (const issue of srv.issues) {
        result.push({
          _key: `srv-${srv.service_id}-${issue}`,
          service_id: srv.service_id,
          service_id_hex: srv.service_id_hex,
          service_name: srv.service_name || '',
          eventgroup_id: null,
          event_name: '—',
          has_offer: srv.has_offer,
          subscribed: false,
          notification_count: '—',
          issue,
          _level: 'service',
        })
      }
    }
    // Eventgroup 行
    for (const eg of srv.eventgroups) {
      const level = eg.issues.length > 0 ? 'error' : 'ok'
      result.push({
        _key: `eg-${srv.service_id}-${eg.eventgroup_id}`,
        service_id: srv.service_id,
        service_id_hex: srv.service_id_hex,
        service_name: srv.service_name || '',
        eventgroup_id: eg.eventgroup_id,
        event_name: eg.event_name || '',
        eventgroup_name: eg.eventgroup_name || '',
        has_offer: srv.has_offer,
        subscribed: eg.subscribed,
        subscriber_ecus: eg.client_ecus,
        acked: eg.acked,
        notification_count: eg.notification_count,
        issue: eg.issues.join('; ') || '',
        _level: level,
      })
    }
  }
  return result
})

function rowClass(row) {
  if (row._level === 'error') return 'row-error'
  if (row._level === 'service') return 'row-warn'
  return ''
}

function onJump(eg) {
  if (eg.eventgroup_id == null) return
  emit('jump-signal', {
    service_id: eg.service_id,
    service_label: eg.service_id_hex,
    event_id: eg.eventgroup_id | 0x8000,
    event_label: `0x${(eg.eventgroup_id | 0x8000).toString(16).toUpperCase()}`,
  })
}
</script>

<template>
  <div class="report-panel">
    <div class="report-header">
      <span class="report-title">订阅诊断报告</span>
      <button class="btn-refresh" :disabled="loading" @click="loadReport">
        {{ loading ? '加载中...' : '刷新' }}
      </button>
    </div>

    <!-- 摘要 -->
    <div class="report-summary" v-if="report?.summary">
      <span class="sum-pill">服务数 <b>{{ report.summary.total_services }}</b></span>
      <span class="sum-pill">Offer 冲突 <b>{{ report.summary.conflict_count }}</b></span>
      <span class="sum-pill sum-warn">已订阅但无通知 <b>{{ report.summary.silent_count }}</b></span>
      <span class="sum-pill">有订阅但无 Offer <b>{{ report.summary.no_offer_count }}</b></span>
    </div>

    <!-- 表格 -->
    <div class="report-table-wrap">
      <table class="report-table" v-if="rows.length">
        <thead>
          <tr>
            <th :style="{ width: colWidths.svc + 'px' }">Service<span class="col-resize" @mousedown="onResizeStart('svc', $event)"></span></th>
            <th :style="{ width: colWidths.eg + 'px' }">EG ID<span class="col-resize" @mousedown="onResizeStart('eg', $event)"></span></th>
            <th :style="{ width: colWidths.evt + 'px' }">Event / Group<span class="col-resize" @mousedown="onResizeStart('evt', $event)"></span></th>
            <th :style="{ width: colWidths.offer + 'px' }">Offer<span class="col-resize" @mousedown="onResizeStart('offer', $event)"></span></th>
            <th :style="{ width: colWidths.sub + 'px' }">Subscribe<span class="col-resize" @mousedown="onResizeStart('sub', $event)"></span></th>
            <th :style="{ width: colWidths.notif + 'px' }">通知数<span class="col-resize" @mousedown="onResizeStart('notif', $event)"></span></th>
            <th>问题说明<span class="col-resize" @mousedown="onResizeStart('issue', $event)"></span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r._key" :class="rowClass(r)"
              @click="onJump(r)" :title="r.eventgroup_id != null ? '点击跳转信号曲线' : ''">
            <td class="mono">{{ fmtSvc(r) }}</td>
            <td class="mono" :class="{ 'is-link': r.eventgroup_id != null }">{{ fmtEg(r) }}</td>
            <td class="mono" :class="{ 'is-link': r.eventgroup_id != null }" style="font-size:11px">{{ fmtEvtGroup(r) || '—' }}</td>
            <td><span class="yn" :class="r.has_offer ? 'yn-yes' : 'yn-no'">{{ r.has_offer ? '✓' : '✗' }}</span></td>
            <td><span class="yn" :class="r.subscribed ? 'yn-yes' : 'yn-no'">{{ r.subscribed ? '✓' : '✗' }}</span></td>
            <td class="mono" style="text-align:right">{{ r.notification_count }}</td>
            <td class="issue-cell">{{ r.issue || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!loading" class="empty">暂无诊断数据</div>
    </div>
  </div>
</template>

<style scoped>
.report-panel { display: flex; flex-direction: column; height: 100%; }
.report-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px; background: linear-gradient(180deg, #f9fbfd, #f1f5f9);
  border-bottom: 1px solid #e5ebf2; flex-shrink: 0;
}
.report-title { font-weight: 700; font-size: 14px; color: #303133; }
.btn-refresh {
  padding: 5px 16px; border: 1px solid #d0d8e4; background: #fff;
  border-radius: 6px; cursor: pointer; font-size: 12px; color: #606266;
}
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }
.report-summary { display: flex; gap: 8px; padding: 8px 14px; flex-shrink: 0; flex-wrap: wrap; }
.sum-pill {
  display: inline-flex; align-items: center; min-height: 26px; padding: 0 10px;
  border-radius: 6px; background: #f4f5f7; border: 1px solid #e0e3e9; font-size: 12px; color: #51606f;
}
.sum-pill b { color: #303133; margin-left: 4px; }
.sum-warn { background: #fef6ed; border-color: #f0d199; color: #b88230; }
.sum-warn b { color: #e6a23c; }
.report-table-wrap { flex: 1; overflow: auto; }
.report-table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.col-resize {
  position: absolute; right: 0; top: 0; bottom: 0; width: 6px; cursor: col-resize;
  background: transparent; transition: background .15s;
}
.col-resize:hover { background: #409eff; }
.report-table th { position: relative; }
.report-table th {
  position: sticky; top: 0; background: #f7fafd; padding: 7px 8px;
  text-align: left; border-bottom: 1px solid #e5ebf2; font-weight: 700; z-index: 1;
}
.report-table td { padding: 6px 8px; border-bottom: 1px solid #f1f4f8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mono { font-family: 'Consolas','Courier New',monospace; }
.yn { font-weight: 700; }
.yn-yes { color: #67c23a; }
.yn-no { color: #c0c4cc; }
.issue-cell { color: #f56c6c; font-size: 12px; white-space: normal; word-break: break-all; }
.row-error { background: #fef5f5; }
.row-error:hover { background: #fde8e8; }
.row-warn { background: #fef9f0; }
.row-warn:hover { background: #fdf3e0; }
.is-link { color: #409eff; cursor: pointer; }
.is-link:hover { text-decoration: underline; }
.empty { color: #909399; text-align: center; padding: 60px 0; font-size: 15px; }
</style>
