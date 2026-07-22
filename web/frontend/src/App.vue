<script setup>
import { ref, reactive, onUnmounted, watch } from 'vue'
import UploadBar from './components/UploadBar.vue'
import MessageTable from './components/MessageTable.vue'
import ParseTree from './components/ParseTree.vue'
import SignalTiming from './components/SignalTiming.vue'
import SubscriptionReport from './components/SubscriptionReport.vue'
import { fetchMessages, fetchMessageDetail, deleteSession } from './api'

const SPLIT_STORAGE_KEY = 'someip-ui-split-percent'

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
</script>

<template>
  <div class="app-shell">
    <UploadBar @parsed="onParsed" :loading="loading || uploading"
               v-model:uploading="uploading"
               :sessionId="sessionId" :hasExport="hasExport" />
    <!-- 进度条：上传解析阶段（动画） + 消息加载阶段（填充） -->
    <div class="progress-bar" v-if="uploading || loading">
      <div v-if="uploading" class="progress-indeterminate"></div>
      <div v-else class="progress-fill" :style="{ width: progress + '%' }"></div>
      <span class="progress-text">
        {{ uploading ? '后台解析中，请耐心等待...' : (progressText || '加载中...') }}
      </span>
    </div>
    <section class="top-strip" v-if="sessionId">
      <nav class="tab-bar">
        <button class="tab-btn" :class="{ active: currentTab === 'parse' }" @click="currentTab = 'parse'">
          报文解析
        </button>
        <button class="tab-btn" :class="{ active: currentTab === 'signal' }" @click="currentTab = 'signal'">
          信号时序
        </button>
        <button class="tab-btn" :class="{ active: currentTab === 'subscription' }" @click="currentTab = 'subscription'">
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
      <SignalTiming :sessionId="sessionId" :prefill="signalPrefill" />
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
  font-family: Inter, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  background: #101827;
  color: #172033;
}
button, input { font: inherit; }
.mono { font-family: Consolas, 'Courier New', monospace; }
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 780px;
  background: radial-gradient(circle at top left, #1e3a5f 0, #101827 34%, #0a0f1c 100%);
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
  border: 1px solid rgba(148, 163, 184, .28);
  border-radius: 7px;
  box-shadow: 0 18px 40px rgba(0, 0, 0, .25);
}
.pane-left { min-width: 320px; background: #f8fafc; }
.pane-right { min-width: 420px; background: #0f172a; }
.splitter {
  width: 12px;
  cursor: col-resize;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.splitter-handle {
  width: 3px;
  height: 86px;
  border-radius: 3px;
  background: #475569;
}
.splitter:hover .splitter-handle { background: #60a5fa; }
.progress-bar {
  height: 24px;
  background: #0f172a;
  position: relative;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  overflow: hidden;
  border-bottom: 1px solid rgba(148, 163, 184, .18);
}
.progress-fill { height: 100%; background: #38bdf8; transition: width .3s ease; }
.progress-text {
  position: absolute;
  width: 100%;
  text-align: center;
  font-size: 12px;
  color: #dbeafe;
  font-weight: 750;
}
.progress-indeterminate {
  height: 100%;
  width: 28%;
  background: linear-gradient(90deg, #2563eb, #22d3ee);
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
  padding: 10px 12px 0;
  flex-shrink: 0;
}
.tab-bar {
  display: flex;
  gap: 5px;
  flex-shrink: 0;
}
.tab-btn {
  min-height: 34px;
  padding: 0 16px;
  border: 1px solid rgba(148, 163, 184, .3);
  background: rgba(15, 23, 42, .76);
  border-radius: 6px 6px 0 0;
  cursor: pointer;
  font-size: 13px;
  color: #cbd5e1;
  font-weight: 800;
  transition: background .15s, color .15s, border-color .15s;
}
.tab-btn.active {
  background: #f8fafc;
  color: #0f172a;
  border-color: #f8fafc;
}
.tab-btn:hover:not(.active) { color: #ffffff; border-color: #60a5fa; }
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
  background: rgba(15, 23, 42, .72);
  border: 1px solid rgba(148, 163, 184, .28);
  border-radius: 5px;
  font-size: 12px;
  color: #cbd5e1;
  font-weight: 750;
}
.overview-pill.is-ok { color: #86efac; border-color: #166534; background: rgba(5, 46, 26, .82); }
@media (max-width: 900px) {
  .app-shell { min-width: 0; }
  .top-strip { flex-direction: column; align-items: stretch; gap: 8px; }
  .overview-bar { justify-content: flex-start; padding-bottom: 0; }
  .workspace { flex-direction: column; padding: 10px; gap: 10px; }
  .pane-left, .pane-right { width: 100% !important; min-width: 0; min-height: 300px; }
  .splitter { display: none; }
}
</style>
