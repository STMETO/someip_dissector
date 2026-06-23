<script setup>
import { ref, computed, watch } from 'vue'
import { fetchSubscriptionReport } from '../api'

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
        eventgroup_id: eg.eventgroup_id,
        event_name: eg.event_name || `EventGroup ${eg.eventgroup_id}`,
        has_offer: srv.has_offer,
        subscribed: eg.subscribed,
        subscriber_ecus: eg.subscriber_ecus,
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
  const mask = eg.eventgroup_id | 0x8000
  emit('jump-signal', {
    service_id: eg.service_id,
    service_label: eg.service_id_hex,
    event_id: mask,
    event_label: `0x${mask.toString(16).toUpperCase()}`,
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
      <span class="sum-pill">服务 {{ report.summary.total_services }}</span>
      <span class="sum-pill">冲突 <b>{{ report.summary.conflict_count }}</b></span>
      <span class="sum-pill sum-warn">静默 <b>{{ report.summary.silent_count }}</b></span>
      <span class="sum-pill">无Offer {{ report.summary.no_offer_count }}</span>
    </div>

    <!-- 表格 -->
    <div class="report-table-wrap">
      <table class="report-table" v-if="rows.length">
        <thead>
          <tr>
            <th style="width:80px">Service ID</th>
            <th style="width:70px">EG ID</th>
            <th style="width:180px">Event 名称</th>
            <th style="width:55px">Offer</th>
            <th style="width:65px">Subscribe</th>
            <th style="width:55px">通知数</th>
            <th>问题说明</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r._key" :class="rowClass(r)"
              @click="onJump(r)" :title="r.eventgroup_id != null ? '点击跳转信号曲线' : ''">
            <td class="mono">{{ r.service_id_hex }}</td>
            <td class="mono">{{ r.eventgroup_id != null ? '0x' + r.eventgroup_id.toString(16).toUpperCase().padStart(4, '0') : '—' }}</td>
            <td class="mono" :class="{ 'is-link': r.eventgroup_id != null }">{{ r.event_name }}</td>
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
