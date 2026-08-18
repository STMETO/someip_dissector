<script setup>
import { computed, nextTick, ref, reactive, onMounted, onUnmounted, watch } from 'vue'
import UploadBar from './components/UploadBar.vue'
import AiAssistant from './components/AiAssistant.vue'
import SessionSwitcher from './components/SessionSwitcher.vue'
import MessageTable from './components/MessageTable.vue'
import ParseTree from './components/ParseTree.vue'
import SignalTiming from './components/SignalTiming.vue'
import SubscriptionReport from './components/SubscriptionReport.vue'
import { cleanupSessions, fetchMessages, fetchMessageDetail, fetchSessions, deleteSession, persistSession, unpersistSession } from './api'

const SPLIT_STORAGE_KEY = 'someip-ui-split-percent-v3'
const THEME_STORAGE_KEY = 'someip-ui-theme'
const DEFAULT_SPLIT_PERCENT = 50

const sessionId = ref('')
const summary = reactive({ total_messages: 0, parsed_count: 0 })
const hasExport = ref(false)
const activeTimings = ref({})
const savedSessions = ref([])
const sessionsLoading = ref(false)
const pendingDeleteSession = ref(null)
const actionBusySessionIds = ref(new Set())
const uploadStartedFromSessionId = ref('')

const messages = ref([])
const selectedMsg = ref(null)
const loading = ref(false)      // 消息列表加载中
const uploading = ref(false)    // 上传+后台解析中
const searchText = ref('')
const progress = ref(0)         // 0-100, 消息加载进度
const progressText = ref('')
const currentTab = ref('parse')  // 'parse' | 'signal' | 'subscription'
const parsePaneMode = ref('split') // 'list' | 'split' | 'tree'
const signalPrefill = ref(null) // 从诊断页跳转时预填参数
const theme = ref(_loadTheme())
const assistantOpen = ref(false)
const messageTableRef = ref(null)
const parseWorkspaceRef = ref(null)
const subscriptionFocus = ref(null)
let navigationToken = 0
let activationRequestId = 0

const activePcapName = computed(() => (
  savedSessions.value.find(item => item.session_id === sessionId.value)?.pcap_name || ''
))

const timingOverview = computed(() => {
  const t = activeTimings.value || {}
  return {
    total: _formatDuration(t.upload_total_ms || t.pipeline_total_ms),
    arxml: _formatDuration(t.arxml_compile_ms),
    pcap: _formatDuration(t.pcap_parse_ms),
    deserialize: _formatDuration(t.payload_deserialize_ms),
    render: _formatDuration(t.frontend_render_ms),
    queryIndex: _formatDuration(t.query_index_ms || t.query_index_restore_ms),
  }
})

// 主题状态集中在页面根节点，避免各业务组件分别维护明暗模式。
watch(theme, (value) => {
  document.documentElement.dataset.theme = value
  window.localStorage.setItem(THEME_STORAGE_KEY, value)
}, { immediate: true })

// 切换会话时回到解析页
watch(sessionId, () => {
  currentTab.value = 'parse'
  signalPrefill.value = null
  subscriptionFocus.value = null
})

// 解析新文件可能耗时较长。记录上传开始时所在的会话，避免用户
// 在解析期间切到旧记录后，又被上传完成事件强制切回新记录。
watch(uploading, (now, prev) => {
  if (now && !prev) {
    uploadStartedFromSessionId.value = sessionId.value
  }
})

onMounted(() => {
  loadSessions()
  window.addEventListener('beforeunload', releaseSessions)
})

function onJumpToSignal(params) {
  signalPrefill.value = { ...params, navigation_token: ++navigationToken }
  currentTab.value = 'signal'
}

async function onNavigateMessage(link) {
  const index = Number(link?.message_index)
  if (!Number.isInteger(index)) return
  currentTab.value = 'parse'
  parsePaneMode.value = 'split'
  searchText.value = ''
  await nextTick()
  const summaryRow = messages.value.find(item => Number(item.index) === index)
  if (!summaryRow) return
  await messageTableRef.value?.revealMessage(index)
  await onSelect(summaryRow)
}

function onNavigateService(link) {
  const serviceId = Number(link?.service_id)
  if (!Number.isInteger(serviceId)) return
  subscriptionFocus.value = {
    service_id: serviceId,
    navigation_token: ++navigationToken,
  }
  currentTab.value = 'subscription'
}

function onNavigateEventgroup(link) {
  const serviceId = Number(link?.service_id)
  const eventgroupId = Number(link?.eventgroup_id)
  if (!Number.isInteger(serviceId) || !Number.isInteger(eventgroupId)) return
  subscriptionFocus.value = {
    service_id: serviceId,
    eventgroup_id: eventgroupId,
    navigation_token: ++navigationToken,
  }
  currentTab.value = 'subscription'
}

function onNavigateSignal(link) {
  const serviceId = Number(link?.service_id)
  if (!Number.isInteger(serviceId)) return
  // 空值不能直接交给 Number；Number(null) 会得到 0，进而误选 Event 0。
  const eventId = link?.event_id == null || link.event_id === ''
    ? null
    : Number(link.event_id)
  onJumpToSignal({
    service_id: serviceId,
    event_id: Number.isInteger(eventId) ? eventId : null,
    field_path: link?.field_path || '',
    start_time: link?.start_time,
    end_time: link?.end_time,
  })
}

// 分割条位置 (左栏百分比)
const splitPercent = ref(_loadSplitPercent())
const dragging = ref(false)

function onDragStart(e) {
  dragging.value = true
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', onDragEnd)
}
function onDrag(e) {
  const rect = parseWorkspaceRef.value?.getBoundingClientRect()
  if (!rect?.width) return
  // AI 面板打开后主工作区不再等于窗口宽度，必须以解析区自身为基准。
  const pct = ((e.clientX - rect.left) / rect.width) * 100
  splitPercent.value = Math.max(34, Math.min(72, pct))
}
function onDragEnd() {
  dragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', onDragEnd)
  window.localStorage.setItem(SPLIT_STORAGE_KEY, String(splitPercent.value))
}

function resetSplit() {
  splitPercent.value = DEFAULT_SPLIT_PERCENT
  window.localStorage.setItem(SPLIT_STORAGE_KEY, String(splitPercent.value))
}

async function onParsed(res) {
  uploading.value = false
  await loadSessions()
  const parsedSession = res.session || {
    session_id: res.session_id,
    summary: res.summary,
    has_export: res.has_export,
  }
  const userStayedOnSameSession = sessionId.value === uploadStartedFromSessionId.value
  if (!sessionId.value || userStayedOnSameSession) {
    await activateSession(parsedSession)
  }
  uploadStartedFromSessionId.value = ''
}

async function loadSessions() {
  sessionsLoading.value = true
  try {
    savedSessions.value = await fetchSessions()
  } finally {
    sessionsLoading.value = false
  }
}

async function activateSession(item) {
  const sid = typeof item === 'string' ? item : item?.session_id
  if (!sid) return
  const requestId = ++activationRequestId
  const meta = typeof item === 'string'
    ? savedSessions.value.find(s => s.session_id === sid)
    : item

  sessionId.value = sid
  Object.assign(summary, meta?.summary || { total_messages: 0, parsed_count: 0 })
  hasExport.value = meta?.has_export !== false
  activeTimings.value = meta?.timings || {}
  selectedMsg.value = null
  messages.value = []
  searchText.value = ''
  loading.value = true
  progress.value = 0
  progressText.value = '加载消息列表中...'
  const timer = setInterval(() => {
    if (progress.value < 90) { progress.value += 10 }
  }, 200)
  try {
    const nextMessages = await fetchMessages(sid)
    if (requestId !== activationRequestId) return
    messages.value = nextMessages
    if (!meta?.summary) {
      Object.assign(summary, {
        total_messages: nextMessages.length,
        parsed_count: nextMessages.filter(m => m.parse_status !== 'unresolved').length,
      })
    }
  } finally {
    clearInterval(timer)
    if (requestId === activationRequestId) {
      progress.value = 100
      progressText.value = ''
      loading.value = false
    }
  }
}

function removeLocalSession(item) {
  const sid = typeof item === 'string' ? item : item?.session_id
  if (!sid) return
  pendingDeleteSession.value = typeof item === 'string'
    ? savedSessions.value.find(row => row.session_id === sid) || { session_id: sid }
    : item
}

function cancelDeleteLocalSession() {
  pendingDeleteSession.value = null
}

async function confirmDeleteLocalSession() {
  const sid = pendingDeleteSession.value?.session_id
  if (!sid) return
  pendingDeleteSession.value = null
  await withSessionBusy(sid, () => deleteSession(sid))
  savedSessions.value = savedSessions.value.filter(row => row.session_id !== sid)
  if (sid !== sessionId.value) return

  const next = savedSessions.value[0]
  if (next) {
    await activateSession(next)
  } else {
    clearActiveSession()
  }
}

async function saveSessionRecord(sid) {
  try {
    const next = await withSessionBusy(sid, () => persistSession(sid))
    upsertSessionRow(next)
    if (sid === sessionId.value) {
      hasExport.value = true
      activeTimings.value = next.timings || {}
    }
  } catch (e) {
    alert('保存记录失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function unsaveSessionRecord(sid) {
  try {
    const next = await withSessionBusy(sid, () => unpersistSession(sid))
    upsertSessionRow(next)
    if (sid === sessionId.value) {
      hasExport.value = false
      activeTimings.value = next.timings || {}
    }
  } catch (e) {
    alert('取消保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

function upsertSessionRow(next) {
  savedSessions.value = [
    next,
    ...savedSessions.value.filter(item => item.session_id !== next.session_id),
  ].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
}

async function withSessionBusy(sid, task) {
  const busy = new Set(actionBusySessionIds.value)
  busy.add(sid)
  actionBusySessionIds.value = busy
  try {
    return await task()
  } finally {
    const next = new Set(actionBusySessionIds.value)
    next.delete(sid)
    actionBusySessionIds.value = next
  }
}

function clearActiveSession() {
  activationRequestId += 1
  sessionId.value = ''
  Object.assign(summary, { total_messages: 0, parsed_count: 0 })
  hasExport.value = false
  activeTimings.value = {}
  messages.value = []
  selectedMsg.value = null
  searchText.value = ''
  loading.value = false
}

async function onSelect(msg) {
  try {
    selectedMsg.value = await fetchMessageDetail(sessionId.value, msg.index)
  } catch { /* ignore */ }
}

onUnmounted(() => {
  window.removeEventListener('beforeunload', releaseSessions)
})

function releaseSessions() {
  cleanupSessions().catch(() => {})
}

function _loadSplitPercent() {
  const raw = window.localStorage.getItem(SPLIT_STORAGE_KEY)
  const parsed = Number(raw)
  if (Number.isFinite(parsed) && parsed >= 34 && parsed <= 72) {
    return parsed
  }
  return DEFAULT_SPLIT_PERCENT
}

function _loadTheme() {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function _formatDuration(ms) {
  const value = Number(ms)
  if (!Number.isFinite(value) || value <= 0) return '-'
  if (value < 1000) return `${Math.round(value)} ms`
  if (value < 60000) return `${(value / 1000).toFixed(2)} s`
  return `${(value / 60000).toFixed(1)} min`
}
</script>

<template>
  <div class="app-shell">
    <UploadBar @parsed="onParsed" :loading="loading || uploading"
               v-model:uploading="uploading"
               v-model:theme="theme"
               :sessionId="sessionId" :hasExport="hasExport">
      <template #session-switcher>
        <SessionSwitcher
          :sessions="savedSessions"
          :activeId="sessionId"
          :loading="sessionsLoading"
          :busyIds="[...actionBusySessionIds]"
          @select="activateSession"
          @delete="removeLocalSession"
          @persist="saveSessionRecord"
          @unpersist="unsaveSessionRecord"
          @refresh="loadSessions"
        />
      </template>
      <template #assistant-trigger>
        <button
          type="button"
          class="assistant-launch"
          :aria-pressed="assistantOpen"
          @click="assistantOpen = !assistantOpen"
        >AI 助手</button>
      </template>
    </UploadBar>
    <!-- 进度条：上传解析阶段（动画） + 消息加载阶段（填充） -->
    <div class="progress-bar" v-if="uploading || loading">
      <div v-if="uploading" class="progress-indeterminate"></div>
      <div v-else class="progress-fill" :style="{ width: progress + '%' }"></div>
      <span class="progress-text">
        {{ uploading ? '后台解析中，请耐心等待...' : (progressText || '加载中...') }}
      </span>
    </div>
    <div class="content-stage" :class="{ 'has-assistant': assistantOpen }">
      <div class="content-main">
        <main v-if="!sessionId" class="empty-workspace">
          <div class="empty-protocol mono">SOME/IP</div>
          <h1>未选择解析记录</h1>
          <p>选择 PCAP 抓包及对应的 ARXML 定义后开始解析。</p>
          <div class="empty-requirements" aria-label="所需文件">
            <span>PCAP</span>
            <span>ARXML</span>
          </div>
        </main>
        <section class="top-strip" v-if="sessionId">
          <nav class="tab-bar">
            <button class="tab-btn" :aria-pressed="currentTab === 'parse'" :class="{ active: currentTab === 'parse' }" @click="currentTab = 'parse'">
              报文解析
            </button>
            <button class="tab-btn" :aria-pressed="currentTab === 'signal'" :class="{ active: currentTab === 'signal' }" @click="currentTab = 'signal'">
              信号时序
            </button>
            <button class="tab-btn" :aria-pressed="currentTab === 'subscription'" :class="{ active: currentTab === 'subscription' }" @click="currentTab = 'subscription'">
              订阅诊断
            </button>
          </nav>
          <div v-if="currentTab === 'parse'" class="parse-mode-switch" role="group" aria-label="报文解析布局">
            <button
              type="button"
              :aria-pressed="parsePaneMode === 'list'"
              :class="{ active: parsePaneMode === 'list' }"
              title="仅显示消息列表"
              @click="parsePaneMode = 'list'"
            >列表</button>
            <button
              type="button"
              :aria-pressed="parsePaneMode === 'split'"
              :class="{ active: parsePaneMode === 'split' }"
              title="同时显示消息列表和解析树"
              @click="parsePaneMode = 'split'"
            >双栏</button>
            <button
              type="button"
              :aria-pressed="parsePaneMode === 'tree'"
              :class="{ active: parsePaneMode === 'tree' }"
              title="仅显示解析树"
              @click="parsePaneMode = 'tree'"
            >树形</button>
          </div>
          <section class="overview-bar">
            <span class="overview-pill mono">会话 {{ sessionId }}</span>
            <span class="overview-pill">报文 {{ summary.total_messages || 0 }}</span>
            <span class="overview-pill is-ok">已解析 {{ summary.parsed_count || 0 }}</span>
            <span class="overview-pill">导出 {{ hasExport ? '开启' : '关闭' }}</span>
            <span class="overview-pill">总耗时 {{ timingOverview.total }}</span>
            <span class="overview-pill">ARXML {{ timingOverview.arxml }}</span>
            <span class="overview-pill">PCAP {{ timingOverview.pcap }}</span>
            <span class="overview-pill">反序列化 {{ timingOverview.deserialize }}</span>
            <span class="overview-pill">树形渲染 {{ timingOverview.render }}</span>
            <span class="overview-pill">查询索引 {{ timingOverview.queryIndex }}</span>
          </section>
        </section>
        <!-- 报文解析视图：网格列会自动扣除中间分隔条宽度。 -->
        <div
          ref="parseWorkspaceRef"
          class="workspace parse-workspace"
          :class="`pane-mode-${parsePaneMode}`"
          v-show="sessionId && currentTab === 'parse'"
          :style="{ '--list-pane-width': splitPercent + '%' }"
        >
          <div v-show="parsePaneMode !== 'tree'" class="pane pane-left">
            <MessageTable ref="messageTableRef" :messages="messages" :loading="loading"
                          :selectedIndex="selectedMsg?.index"
                          v-model:searchText="searchText"
                          @select="onSelect" />
          </div>
          <div v-show="parsePaneMode === 'split'" class="splitter" @mousedown.prevent="onDragStart" @dblclick="resetSplit" title="拖动调整比例，双击恢复默认布局">
            <span class="splitter-handle"></span>
          </div>
          <div v-show="parsePaneMode !== 'list'" class="pane pane-right">
            <ParseTree :message="selectedMsg" :key="selectedMsg?.index" />
          </div>
        </div>
        <!-- 信号时序视图 -->
        <div class="workspace" v-show="sessionId && currentTab === 'signal'">
          <SignalTiming
            :sessionId="sessionId"
            :prefill="signalPrefill"
            :theme="theme"
            @navigate-message="onNavigateMessage"
          />
        </div>
        <!-- 订阅诊断视图 -->
        <div class="workspace" v-show="sessionId && currentTab === 'subscription'">
          <SubscriptionReport
            :sessionId="sessionId"
            :focus="subscriptionFocus"
            @jump-signal="onJumpToSignal"
          />
        </div>
      </div>
      <AiAssistant
        v-model:open="assistantOpen"
        :sessionId="sessionId"
        :pcapName="activePcapName"
        :persistent="hasExport"
        @navigate-message="onNavigateMessage"
        @navigate-service="onNavigateService"
        @navigate-eventgroup="onNavigateEventgroup"
        @navigate-signal="onNavigateSignal"
      />
    </div>
    <Teleport to="body">
      <div v-if="pendingDeleteSession" class="confirm-layer" role="presentation">
        <button
          class="confirm-backdrop"
          type="button"
          aria-label="取消删除"
          @click="cancelDeleteLocalSession"
        ></button>
        <section class="confirm-dialog" role="alertdialog" aria-modal="true" aria-label="删除本地解析记录">
          <header>
            <strong>删除本地记录？</strong>
            <span>该解析记录将从当前页面会话中彻底删除。</span>
          </header>
          <div class="confirm-target">
            <span :title="pendingDeleteSession.pcap_name">{{ pendingDeleteSession.pcap_name || 'capture' }}</span>
            <small class="mono">{{ pendingDeleteSession.session_id }}</small>
          </div>
          <footer>
            <button type="button" class="btn-lite" @click="cancelDeleteLocalSession">取消</button>
            <button type="button" class="btn-danger" @click="confirmDeleteLocalSession">删除</button>
          </footer>
        </section>
      </div>
    </Teleport>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app {
  height: 100%;
  overflow: hidden;
  font-family: var(--font-sans);
  background: var(--canvas);
  color: var(--text-primary);
}
button, input, select { font: inherit; }
.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 780px;
  background: var(--canvas);
}
.content-stage {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  overflow: hidden;
}
.content-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.assistant-launch {
  min-height: 34px;
  padding: 0 12px;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-control);
  background: var(--accent-soft);
  color: var(--accent);
  cursor: pointer;
  font-size: 12px;
  font-weight: 900;
  white-space: nowrap;
}
.assistant-launch:hover,
.assistant-launch[aria-pressed="true"] {
  border-color: var(--accent);
  background: var(--surface-selected);
  color: var(--accent-hover);
}
.empty-workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  text-align: center;
  color: var(--text-secondary);
}
.empty-protocol {
  margin-bottom: 14px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 900;
}
.empty-workspace h1 {
  color: var(--text-primary);
  font-size: 24px;
  line-height: 1.2;
}
.empty-workspace p {
  margin-top: 8px;
  max-width: 46ch;
  font-size: 13px;
}
.empty-requirements {
  display: flex;
  gap: 8px;
  margin-top: 18px;
}
.empty-requirements span {
  padding: 5px 9px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 800;
}
.confirm-layer {
  position: fixed;
  inset: 0;
  z-index: 130;
  display: grid;
  place-items: center;
  padding: 20px;
}
.confirm-backdrop {
  position: absolute;
  inset: 0;
  border: 0;
  background: rgba(10, 12, 16, .36);
}
.confirm-dialog {
  position: relative;
  width: min(420px, calc(100vw - 32px));
  overflow: hidden;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  box-shadow: var(--shadow-popover);
}
.confirm-dialog header {
  padding: 14px 15px 11px;
  border-bottom: 1px solid var(--border);
  background: var(--danger-soft);
}
.confirm-dialog header strong {
  display: block;
  color: var(--danger);
  font-size: 15px;
  font-weight: 900;
}
.confirm-dialog header span {
  display: block;
  margin-top: 4px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}
.confirm-target {
  display: grid;
  gap: 4px;
  padding: 13px 15px;
}
.confirm-target span,
.confirm-target small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.confirm-target span {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 900;
}
.confirm-target small {
  color: var(--text-tertiary);
  font-size: 11px;
}
.confirm-dialog footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 11px 15px 14px;
  border-top: 1px solid var(--border);
  background: var(--surface-subtle);
}
.confirm-dialog footer button {
  min-height: 31px;
  padding: 0 12px;
  border-radius: var(--radius-control);
  cursor: pointer;
  font-size: 12px;
  font-weight: 850;
}
.confirm-dialog .btn-lite {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-secondary);
}
.confirm-dialog .btn-lite:hover {
  border-color: var(--accent-border);
  color: var(--accent);
  background: var(--accent-soft);
}
.confirm-dialog .btn-danger {
  border: 1px solid var(--danger);
  background: var(--danger);
  color: var(--accent-contrast);
}
.confirm-dialog .btn-danger:hover {
  border-color: var(--danger);
  background: var(--danger-soft);
  color: var(--danger);
}
.workspace {
  flex: 1;
  display: flex;
  overflow: hidden;
  padding: 10px 12px 12px;
  gap: 0;
  min-height: 0;
}
.parse-workspace {
  display: grid;
  grid-template-columns: minmax(0, var(--list-pane-width)) 12px minmax(0, 1fr);
}
.parse-workspace.pane-mode-list,
.parse-workspace.pane-mode-tree {
  grid-template-columns: minmax(0, 1fr);
}
.pane {
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  box-shadow: var(--shadow-panel);
}
.pane-left { min-width: 320px; background: var(--surface); }
.pane-right { min-width: 360px; background: var(--surface); }
.content-stage.has-assistant .pane-left,
.content-stage.has-assistant .pane-right { min-width: 0; }
.splitter {
  width: 12px;
  cursor: col-resize;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.splitter-handle {
  width: 2px;
  height: 72px;
  border-radius: 2px;
  background: var(--border-strong);
  transition: background .16s ease, width .16s ease;
}
.splitter:hover .splitter-handle { width: 3px; background: var(--accent); }
.progress-bar {
  height: 24px;
  background: var(--surface-muted);
  position: relative;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  overflow: hidden;
  border-bottom: 1px solid var(--border);
}
.progress-fill { height: 100%; background: var(--accent); transition: width .3s ease; }
.progress-text {
  position: absolute;
  width: 100%;
  text-align: center;
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 750;
}
.progress-indeterminate {
  height: 100%;
  width: 28%;
  background: var(--accent);
  animation: progress-slide 1.35s ease-in-out infinite;
}
@keyframes progress-slide {
  0% { margin-left: -30%; }
  100% { margin-left: 100%; }
}
.top-strip {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px 0;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
}
.tab-bar {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
.parse-mode-switch {
  display: inline-grid;
  grid-template-columns: repeat(3, auto);
  flex-shrink: 0;
  align-self: center;
  margin-bottom: 8px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-muted);
}
.parse-mode-switch button {
  min-width: 42px;
  min-height: 27px;
  padding: 0 8px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 11px;
  font-weight: 850;
  white-space: nowrap;
}
.parse-mode-switch button:hover { color: var(--text-primary); }
.parse-mode-switch button.active {
  background: var(--surface-raised);
  color: var(--accent);
  box-shadow: 0 1px 3px rgba(30, 38, 50, .12);
}
.tab-btn {
  min-height: 36px;
  padding: 0 16px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  border-radius: 0;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 800;
  transition: background .15s, color .15s, border-color .15s;
}
.tab-btn.active {
  color: var(--accent);
  border-color: var(--accent);
}
.tab-btn:hover:not(.active) { color: var(--text-primary); background: var(--surface-hover); }
.overview-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  justify-content: flex-end;
  align-items: center;
  flex: 1 1 auto;
  min-width: 0;
  margin-left: auto;
  padding-bottom: 8px;
}
.overview-pill {
  display: inline-flex;
  align-items: center;
  min-height: 27px;
  padding: 0 9px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 750;
}
.overview-pill.is-ok { color: var(--success); border-color: var(--success-border); background: var(--success-soft); }
@media (max-width: 900px) {
  .app-shell { min-width: 0; }
  .top-strip { flex-direction: column; align-items: stretch; gap: 8px; }
  .parse-mode-switch { align-self: flex-start; margin-bottom: 0; }
  .overview-bar { justify-content: flex-start; padding-bottom: 0; }
  .workspace { flex-direction: column; padding: 10px; gap: 10px; }
  .parse-workspace { display: flex; }
  .pane-left, .pane-right { width: 100% !important; min-width: 0; min-height: 300px; }
  .splitter { display: none; }
  /* 窄屏打开助手时切换到对话视图，避免任何内容覆盖。 */
  .content-stage.has-assistant .content-main { display: none; }
  .content-stage.has-assistant > .assistant-drawer { width: 100% !important; }
}
</style>
