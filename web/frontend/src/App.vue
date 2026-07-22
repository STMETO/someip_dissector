<script setup>
import { ref, reactive, onUnmounted, watch } from 'vue'
import UploadBar from './components/UploadBar.vue'
import MessageTable from './components/MessageTable.vue'
import ParseTree from './components/ParseTree.vue'
import SignalTiming from './components/SignalTiming.vue'
import SubscriptionReport from './components/SubscriptionReport.vue'
import { fetchMessages, fetchMessageDetail, deleteSession } from './api'

const SPLIT_STORAGE_KEY = 'someip-ui-split-percent'
const THEME_STORAGE_KEY = 'someip-ui-theme'

const sessionId = ref('')
const summary = reactive({ total_messages: 0, parsed_count: 0 })
const hasExport = ref(false)

const messages = ref([])
const selectedMsg = ref(null)
const loading = ref(false)      // 消息列表加载中
const uploading = ref(false)    // 上传+后台解析中
const searchText = ref('')
const progress = ref(0)         // 0-100, 消息加载进度
const progressText = ref('')
const currentTab = ref('parse')  // 'parse' | 'signal' | 'subscription'
const signalPrefill = ref(null) // 从诊断页跳转时预填参数
const theme = ref(_loadTheme())

// 主题状态集中在页面根节点，避免各业务组件分别维护明暗模式。
watch(theme, (value) => {
  document.documentElement.dataset.theme = value
  window.localStorage.setItem(THEME_STORAGE_KEY, value)
}, { immediate: true })

// 切换会话时回到解析页
watch(sessionId, () => { currentTab.value = 'parse'; signalPrefill.value = null })

function onJumpToSignal(params) {
  signalPrefill.value = params
  currentTab.value = 'signal'
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
  const pct = (e.clientX / window.innerWidth) * 100
  splitPercent.value = Math.max(30, Math.min(72, pct))
}
function onDragEnd() {
  dragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', onDragEnd)
  window.localStorage.setItem(SPLIT_STORAGE_KEY, String(splitPercent.value))
}

function resetSplit() {
  splitPercent.value = 46
  window.localStorage.setItem(SPLIT_STORAGE_KEY, String(splitPercent.value))
}

async function onParsed(res) {
  uploading.value = false
  sessionId.value = res.session_id
  Object.assign(summary, res.summary)
  hasExport.value = !!res.has_export
  loading.value = true
  progress.value = 0
  progressText.value = '加载消息列表中...'
  const timer = setInterval(() => {
    if (progress.value < 90) { progress.value += 10 }
  }, 200)
  try {
    messages.value = await fetchMessages(sessionId.value)
  } finally {
    clearInterval(timer)
    progress.value = 100
    progressText.value = ''
    loading.value = false
  }
}

async function onSelect(msg) {
  try {
    selectedMsg.value = await fetchMessageDetail(sessionId.value, msg.index)
  } catch { /* ignore */ }
}

onUnmounted(() => {
  if (sessionId.value) deleteSession(sessionId.value).catch(() => {})
})

function _loadSplitPercent() {
  const raw = window.localStorage.getItem(SPLIT_STORAGE_KEY)
  const parsed = Number(raw)
  if (Number.isFinite(parsed) && parsed >= 30 && parsed <= 72) {
    return parsed
  }
  return 46
}

function _loadTheme() {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}
</script>

<template>
  <div class="app-shell">
    <UploadBar @parsed="onParsed" :loading="loading || uploading"
               v-model:uploading="uploading"
               v-model:theme="theme"
               :sessionId="sessionId" :hasExport="hasExport" />
    <!-- 进度条：上传解析阶段（动画） + 消息加载阶段（填充） -->
    <div class="progress-bar" v-if="uploading || loading">
      <div v-if="uploading" class="progress-indeterminate"></div>
      <div v-else class="progress-fill" :style="{ width: progress + '%' }"></div>
      <span class="progress-text">
        {{ uploading ? '后台解析中，请耐心等待...' : (progressText || '加载中...') }}
      </span>
    </div>
    <main v-if="!sessionId" class="empty-workspace">
      <div class="empty-protocol mono">SOME/IP</div>
      <h1>No active capture</h1>
      <p>Select a PCAP capture and its ARXML definition to begin.</p>
      <div class="empty-requirements" aria-label="Required files">
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
      <section class="overview-bar">
        <span class="overview-pill mono">会话 {{ sessionId }}</span>
        <span class="overview-pill">报文 {{ summary.total_messages || 0 }}</span>
        <span class="overview-pill is-ok">已解析 {{ summary.parsed_count || 0 }}</span>
        <span class="overview-pill">导出 {{ hasExport ? '开启' : '关闭' }}</span>
      </section>
    </section>
    <!-- 报文解析视图 -->
    <div class="workspace" v-show="sessionId && currentTab === 'parse'">
      <div class="pane pane-left" :style="{ width: splitPercent + '%' }">
        <MessageTable :messages="messages" :loading="loading"
                      :selectedIndex="selectedMsg?.index"
                      v-model:searchText="searchText"
                      @select="onSelect" />
      </div>
      <div class="splitter" @mousedown.prevent="onDragStart" @dblclick="resetSplit" title="拖动调整比例，双击恢复默认布局">
        <span class="splitter-handle"></span>
      </div>
      <div class="pane pane-right" :style="{ width: (100 - splitPercent) + '%' }">
        <ParseTree :message="selectedMsg" :key="selectedMsg?.index" />
      </div>
    </div>
    <!-- 信号时序视图 -->
    <div class="workspace" v-show="sessionId && currentTab === 'signal'">
      <SignalTiming :sessionId="sessionId" :prefill="signalPrefill" :theme="theme" />
    </div>
    <!-- 订阅诊断视图 -->
    <div class="workspace" v-show="sessionId && currentTab === 'subscription'">
      <SubscriptionReport :sessionId="sessionId" @jump-signal="onJumpToSignal" />
    </div>
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
.workspace {
  flex: 1;
  display: flex;
  overflow: hidden;
  padding: 10px 12px 12px;
  gap: 0;
  min-height: 0;
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
.pane-right { min-width: 420px; background: var(--surface); }
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
  flex-shrink: 0;
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
  .overview-bar { justify-content: flex-start; padding-bottom: 0; }
  .workspace { flex-direction: column; padding: 10px; gap: 10px; }
  .pane-left, .pane-right { width: 100% !important; min-width: 0; min-height: 300px; }
  .splitter { display: none; }
}
</style>
