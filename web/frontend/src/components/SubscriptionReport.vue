<script setup>
import { ref, computed, watch } from 'vue'
import { fetchSubscriptionReport } from '../api'

const props = defineProps({
  sessionId: { type: String, required: true },
})
const emit = defineEmits(['jump-signal'])

const loading = ref(false)
const report = ref(null)
const activeFilter = ref('all')
const expandedServices = ref(new Set())

watch(() => props.sessionId, (sid) => {
  if (sid) loadReport()
}, { immediate: true })

async function loadReport() {
  loading.value = true
  report.value = null
  activeFilter.value = 'all'
  expandedServices.value = new Set()
  try {
    report.value = await fetchSubscriptionReport(props.sessionId)
    expandFiltered()
  } catch {
    report.value = null
  } finally {
    loading.value = false
  }
}

const services = computed(() => report.value?.services || [])

const enhancedServices = computed(() => services.value.map(svc => {
  const clients = uniqueFlat(svc.eventgroups.flatMap(eg => eg.client_ecus || []))
  const ackClients = uniqueFlat(svc.eventgroups.flatMap(eg => eg.ack_ecus || []))
  const issueCount = (svc.issues || []).length + svc.eventgroups.reduce((sum, eg) => sum + (eg.issues?.length || 0), 0)
  const noAck = svc.eventgroups.some(eg => eg.subscribed && !eg.acked)
  const silent = svc.eventgroups.some(eg => eg.subscribed && Number(eg.notification_count || 0) === 0)
  const noOffer = !svc.has_offer && svc.eventgroups.some(eg => eg.subscribed)
  const unsubscribed = svc.has_offer && clients.length === 0
  return { ...svc, clients, ackClients, issueCount, noAck, silent, noOffer, unsubscribed }
}))

const filteredServices = computed(() => enhancedServices.value.filter(svc => {
  if (activeFilter.value === 'all') return true
  if (activeFilter.value === 'conflict') return svc.offer_conflict
  if (activeFilter.value === 'silent') return svc.silent
  if (activeFilter.value === 'no_offer') return svc.noOffer
  if (activeFilter.value === 'unsubscribed') return svc.unsubscribed
  if (activeFilter.value === 'no_ack') return svc.noAck
  return true
}))

const metrics = computed(() => {
  const list = enhancedServices.value
  return {
    all: list.length,
    conflict: list.filter(s => s.offer_conflict).length,
    silent: list.filter(s => s.silent).length,
    no_offer: list.filter(s => s.noOffer).length,
    unsubscribed: list.filter(s => s.unsubscribed).length,
    no_ack: list.filter(s => s.noAck).length,
  }
})

const filterCards = computed(() => [
  { key: 'all', label: '服务数', value: metrics.value.all, tone: 'neutral' },
  { key: 'conflict', label: 'Offer 冲突', value: metrics.value.conflict, tone: 'danger' },
  { key: 'silent', label: '已订阅但无通知', value: metrics.value.silent, tone: 'warning' },
  { key: 'no_offer', label: '有订阅但无 Offer', value: metrics.value.no_offer, tone: 'danger' },
  { key: 'unsubscribed', label: 'Offer 后无订阅', value: metrics.value.unsubscribed, tone: 'muted' },
  { key: 'no_ack', label: 'Subscribe 未 Ack', value: metrics.value.no_ack, tone: 'warning' },
])

function setFilter(key) {
  activeFilter.value = key
  expandFiltered()
}

function toggleService(serviceId) {
  const next = new Set(expandedServices.value)
  if (next.has(serviceId)) next.delete(serviceId)
  else next.add(serviceId)
  expandedServices.value = next
}

function isExpanded(serviceId) {
  return expandedServices.value.has(serviceId)
}

function expandFiltered() {
  expandedServices.value = new Set(filteredServices.value.map(s => s.service_id))
}

function collapseAll() {
  expandedServices.value = new Set()
}

function fmtSvc(svc) {
  return svc.service_name ? `${svc.service_id_hex} (${svc.service_name})` : svc.service_id_hex
}

function fmtEg(eg) {
  if (eg.eventgroup_id == null) return '-'
  const h = '0x' + eg.eventgroup_id.toString(16).toUpperCase().padStart(4, '0')
  return eg.eventgroup_name ? `${h} (${eg.eventgroup_name})` : h
}

function fmtEvt(eg) {
  if (eg.eventgroup_id == null) return '-'
  const notifId = eg.eventgroup_id | 0x8000
  const h = '0x' + notifId.toString(16).toUpperCase().padStart(4, '0')
  return eg.event_name ? `${h} (${eg.event_name})` : h
}

function statusClass(svc) {
  if (svc.offer_conflict || svc.noOffer) return 'status-danger'
  if (svc.silent || svc.noAck || svc.unsubscribed || svc.issueCount) return 'status-warning'
  return 'status-ok'
}

function statusText(svc) {
  if (svc.offer_conflict) return 'Offer conflict'
  if (svc.noOffer) return 'No offer'
  if (svc.noAck) return 'No ack'
  if (svc.silent) return 'Silent'
  if (svc.unsubscribed) return 'No subscriber'
  if (svc.issueCount) return 'Issue'
  return 'Healthy'
}

function onJump(svc, eg) {
  if (eg.eventgroup_id == null || Number(eg.notification_count || 0) <= 0) return
  emit('jump-signal', {
    service_id: svc.service_id,
    service_label: fmtSvc(svc),
    event_id: eg.eventgroup_id | 0x8000,
    event_label: fmtEvt(eg),
  })
}

function uniqueFlat(values) {
  return [...new Set(values.filter(Boolean))].sort()
}
</script>

<template>
  <div class="report-panel">
    <header class="report-header">
      <div>
        <div class="report-title">订阅诊断报告</div>
        <div class="report-subtitle">按 Service 展示 Offer、Subscribe、Ack 与 Notification 链路</div>
      </div>
      <div class="header-actions">
        <button class="btn-lite" :disabled="!filteredServices.length" @click="expandFiltered">展开当前</button>
        <button class="btn-lite" :disabled="!expandedServices.size" @click="collapseAll">收起全部</button>
        <button class="btn-refresh" :disabled="loading" @click="loadReport">
          {{ loading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </header>

    <section class="metric-grid" v-if="report?.summary">
      <button
        v-for="card in filterCards"
        :key="card.key"
        class="metric-card"
        :class="[`tone-${card.tone}`, { active: activeFilter === card.key }]"
        @click="setFilter(card.key)">
        <span class="metric-label">{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </button>
    </section>

    <div class="filter-line" v-if="report?.summary">
      <span>当前过滤：<b>{{ filterCards.find(c => c.key === activeFilter)?.label }}</b></span>
      <span>显示 {{ filteredServices.length }} / {{ enhancedServices.length }} 个 Service</span>
    </div>

    <main class="service-list">
      <div v-if="loading" class="empty">正在生成诊断报告...</div>
      <div v-else-if="!filteredServices.length" class="empty">无匹配诊断数据</div>

      <article v-for="svc in filteredServices" :key="svc.service_id" class="service-card" :class="statusClass(svc)">
        <button class="service-head" @click="toggleService(svc.service_id)">
          <span class="expand-mark">{{ isExpanded(svc.service_id) ? '-' : '+' }}</span>
          <span class="svc-main">
            <span class="svc-name mono">{{ fmtSvc(svc) }}</span>
            <span class="svc-status" :class="statusClass(svc)">{{ statusText(svc) }}</span>
          </span>
          <span class="svc-facts">
            <span>Servers <b>{{ svc.server_ecus.length }}</b></span>
            <span>Clients <b>{{ svc.clients.length }}</b></span>
            <span>EventGroups <b>{{ svc.eventgroups.length }}</b></span>
            <span>Notifications <b>{{ svc.eventgroups.reduce((sum, eg) => sum + Number(eg.notification_count || 0), 0) }}</b></span>
          </span>
        </button>

        <section v-if="isExpanded(svc.service_id)" class="service-body">
          <div class="endpoint-row">
            <div class="endpoint-box">
              <span class="endpoint-title">Offer servers</span>
              <span v-if="svc.server_ecus.length" v-for="server in svc.server_ecus" :key="server" class="endpoint-chip server">{{ server }}</span>
              <span v-else class="endpoint-empty">none</span>
            </div>
            <div class="endpoint-box">
              <span class="endpoint-title">Subscribed clients</span>
              <span v-if="svc.clients.length" v-for="client in svc.clients" :key="client" class="endpoint-chip client">{{ client }}</span>
              <span v-else class="endpoint-empty">none</span>
            </div>
          </div>

          <div v-if="svc.issues.length" class="service-issues">
            <div v-for="issue in svc.issues" :key="issue" class="issue-line">{{ issue }}</div>
          </div>

          <table class="eg-table" v-if="svc.eventgroups.length">
            <thead>
              <tr>
                <th>EventGroup</th>
                <th>Event</th>
                <th>Clients</th>
                <th>Ack</th>
                <th>Notif</th>
                <th>Issue</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="eg in svc.eventgroups" :key="eg.eventgroup_id" :class="{ 'eg-error': eg.issues.length }">
                <td class="mono"><span class="eg-chip">{{ fmtEg(eg) }}</span></td>
                <td class="mono event-cell" :class="{ clickable: Number(eg.notification_count || 0) > 0 }" @click.stop="onJump(svc, eg)">
                  {{ fmtEvt(eg) }}
                </td>
                <td>
                  <span v-if="eg.client_ecus?.length" v-for="client in eg.client_ecus" :key="client" class="client-detail">
                    {{ client }} <small>Subscribed</small>
                  </span>
                  <span v-else class="muted">none</span>
                </td>
                <td><span class="yn" :class="eg.acked ? 'yes' : 'no'">{{ eg.acked ? 'yes' : 'no' }}</span></td>
                <td class="mono notif-count">{{ eg.notification_count }}</td>
                <td class="issue-cell">{{ eg.issues.join('; ') || '-' }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-service">该 Service 有 Offer，但抓包中没有看到 Subscribe EventGroup。</div>
        </section>
      </article>
    </main>
  </div>
</template>

<style scoped>
.report-panel {
  display: flex; flex-direction: column; height: 100%; width: 100%; min-height: 0; min-width: 0;
  background: #f8fafc; color: #172033;
}
.report-header {
  display: flex; justify-content: space-between; align-items: center; gap: 14px;
  padding: 13px 16px; border-bottom: 1px solid #cbd5e1; background: #ffffff; flex-shrink: 0;
}
.report-title { font-weight: 900; font-size: 15px; color: #0f172a; }
.report-subtitle { margin-top: 3px; color: #64748b; font-size: 12px; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.btn-refresh, .btn-lite {
  min-height: 30px; padding: 0 12px; border: 1px solid #cbd5e1; background: #fff;
  border-radius: 5px; cursor: pointer; font-size: 12px; color: #475569; font-weight: 800;
}
.btn-refresh { color: #075985; border-color: #7dd3fc; background: #f0f9ff; }
.btn-refresh:disabled, .btn-lite:disabled { opacity: .45; cursor: not-allowed; }
.metric-grid {
  display: grid; grid-template-columns: repeat(6, minmax(110px, 1fr)); gap: 8px;
  padding: 10px 14px; border-bottom: 1px solid #e2e8f0; background: #f1f5f9; flex-shrink: 0;
}
.metric-card {
  text-align: left; min-height: 58px; border: 1px solid #cbd5e1; border-radius: 7px;
  background: #fff; padding: 8px 10px; cursor: pointer; color: #334155;
}
.metric-card:hover { border-color: #0284c7; box-shadow: 0 0 0 3px rgba(2,132,199,.12); }
.metric-card.active { border-color: #0284c7; background: #e0f2fe; }
.metric-label { display: block; font-size: 12px; color: #64748b; font-weight: 750; }
.metric-card strong { display: block; margin-top: 4px; font-size: 20px; color: #0f172a; }
.tone-danger strong { color: #991b1b; }
.tone-warning strong { color: #92400e; }
.tone-muted strong { color: #475569; }
.filter-line {
  display: flex; justify-content: space-between; gap: 12px; padding: 7px 15px;
  font-size: 12px; color: #64748b; background: #fff; border-bottom: 1px solid #e2e8f0; flex-shrink: 0;
}
.service-list { flex: 1; overflow: auto; padding: 12px 14px 18px; min-height: 0; width: 100%; }
.service-card { width: 100%; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; margin-bottom: 10px; overflow: hidden; }
.service-card.status-danger { border-color: #fca5a5; }
.service-card.status-warning { border-color: #fcd34d; }
.service-card.status-ok { border-color: #bbf7d0; }
.service-head {
  width: 100%; min-height: 50px; display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border: none; background: #fff; cursor: pointer; text-align: left;
}
.service-head:hover { background: #f8fafc; }
.expand-mark {
  width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 5px; border: 1px solid #cbd5e1; background: #f8fafc; font-weight: 900; flex-shrink: 0;
}
.svc-main { display: flex; align-items: center; gap: 9px; min-width: 230px; flex: 1; }
.svc-name { font-weight: 900; color: #0f172a; }
.svc-status { padding: 3px 7px; border-radius: 5px; font-size: 11px; font-weight: 900; border: 1px solid #cbd5e1; }
.svc-status.status-ok { color: #166534; background: #dcfce7; border-color: #86efac; }
.svc-status.status-warning { color: #92400e; background: #fef3c7; border-color: #fbbf24; }
.svc-status.status-danger { color: #991b1b; background: #fee2e2; border-color: #fca5a5; }
.svc-facts { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; color: #64748b; font-size: 12px; }
.svc-facts span { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 5px; padding: 3px 7px; }
.svc-facts b { color: #0f172a; }
.service-body { border-top: 1px solid #e2e8f0; padding: 11px 12px 12px; background: #fbfdff; }
.endpoint-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px; }
.endpoint-box { border: 1px solid #e2e8f0; border-radius: 7px; background: #fff; padding: 8px; min-height: 42px; }
.endpoint-title { display: block; color: #64748b; font-size: 12px; font-weight: 850; margin-bottom: 6px; }
.endpoint-chip, .client-detail {
  display: inline-flex; align-items: center; gap: 5px; margin: 2px 5px 2px 0;
  padding: 3px 7px; border-radius: 5px; font-size: 12px; font-weight: 800;
}
.endpoint-chip.server { color: #075985; background: #e0f2fe; border: 1px solid #7dd3fc; }
.endpoint-chip.client, .client-detail { color: #166534; background: #dcfce7; border: 1px solid #86efac; }
.client-detail small { color: #475569; font-weight: 750; }
.endpoint-empty, .muted { color: #94a3b8; font-size: 12px; }
.service-issues { margin-bottom: 10px; }
.issue-line { color: #991b1b; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 5px; padding: 6px 8px; font-size: 12px; margin-bottom: 5px; }
.eg-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 12px; background: #fff; border: 1px solid #e2e8f0; }
.eg-table th { text-align: left; padding: 7px 8px; background: #e2e8f0; color: #334155; font-weight: 900; }
.eg-table th:nth-child(1) { width: 24%; }
.eg-table th:nth-child(2) { width: 24%; }
.eg-table th:nth-child(3) { width: 23%; }
.eg-table th:nth-child(4) { width: 8%; }
.eg-table th:nth-child(5) { width: 7%; }
.eg-table th:nth-child(6) { width: 14%; }
.eg-table td { padding: 7px 8px; border-top: 1px solid #edf2f7; vertical-align: top; }
.eg-error { background: #fff7ed; }
.eg-chip {
  display: inline-flex; max-width: 100%; align-items: center;
  padding: 4px 7px; border-radius: 5px; border: 1px solid #cbd5e1;
  background: #f8fafc; color: #334155; font-weight: 850;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.event-cell.clickable { color: #0284c7; cursor: pointer; font-weight: 850; }
.event-cell.clickable:hover { text-decoration: underline; }
.yn { font-weight: 900; }
.yn.yes { color: #166534; }
.yn.no { color: #991b1b; }
.notif-count { text-align: right; font-weight: 850; }
.issue-cell { color: #991b1b; white-space: normal; word-break: break-word; }
.empty, .empty-service { color: #64748b; text-align: center; padding: 36px 0; font-size: 13px; }
.empty-service { padding: 12px; background: #fff; border: 1px dashed #cbd5e1; border-radius: 7px; }
.mono { font-family: Consolas, 'Courier New', monospace; }
@media (max-width: 1100px) {
  .metric-grid { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
  .service-head { align-items: flex-start; flex-direction: column; }
  .svc-main { min-width: 0; }
  .svc-facts { justify-content: flex-start; }
}
@media (max-width: 760px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
  .endpoint-row { grid-template-columns: 1fr; }
  .report-header, .filter-line { flex-direction: column; align-items: flex-start; }
}
</style>
