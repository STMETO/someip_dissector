<script setup>
import { ref, reactive, onUnmounted, watch } from 'vue'
import UploadBar from './components/UploadBar.vue'
import MessageTable from './components/MessageTable.vue'
import ParseTree from './components/ParseTree.vue'
import SignalTiming from './components/SignalTiming.vue'
import SubscriptionReport from './components/SubscriptionReport.vue'
import { fetchMessages, fetchMessageDetail, deleteSession, exportUrl } from './api'

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
    <section class="overview-bar" v-if="sessionId">
      <span class="overview-pill mono">会话 {{ sessionId }}</span>
      <span class="overview-pill">报文 {{ summary.total_messages || 0 }}</span>
      <span class="overview-pill is-ok">已解析 {{ summary.parsed_count || 0 }}</span>
      <span class="overview-pill">导出 {{ hasExport ? '开启' : '关闭' }}</span>
    </section>
    <nav class="tab-bar" v-if="sessionId">
      <button class="tab-btn" :class="{ active: currentTab === 'parse' }" @click="currentTab = 'parse'">
        📋 报文解析
      </button>
      <button class="tab-btn" :class="{ active: currentTab === 'signal' }" @click="currentTab = 'signal'">
        📈 信号时序
      </button>
      <button class="tab-btn" :class="{ active: currentTab === 'subscription' }" @click="currentTab = 'subscription'">
        🔍 订阅诊断
      </button>
    </nav>
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
  height: 100%; overflow: hidden; font-family: 'Segoe UI', sans-serif;
  background: linear-gradient(180deg, #edf2f8 0%, #e4eaf1 100%);
  color: #303133;
}
.mono { font-family: 'Consolas','Courier New',monospace; }
.app-shell { display: flex; flex-direction: column; height: 100%; }
.workspace { flex: 1; display: flex; overflow: hidden; padding: 10px; gap: 0; min-height: 0; }
.pane {
  overflow: auto; display: flex; flex-direction: column; min-height: 0;
  background: rgba(255,255,255,0.92); border: 1px solid #d8e0ea; border-radius: 10px;
  box-shadow: 0 8px 24px rgba(31, 45, 61, 0.08);
}
.pane-left { min-width: 280px; }
.pane-right { min-width: 360px; }
.splitter {
  width: 14px; cursor: col-resize; flex-shrink: 0; transition: background .2s;
  display: flex; align-items: center; justify-content: center;
}
.splitter-handle {
  width: 4px; height: 64px; border-radius: 999px;
  background: linear-gradient(180deg, #c4d3e6, #7ea8df);
  box-shadow: 0 0 0 1px rgba(126, 168, 223, 0.2);
}
.splitter:hover .splitter-handle { background: linear-gradient(180deg, #8ec5ff, #409eff); }
.progress-bar {
  height: 24px; background: #ecf5ff; position: relative; flex-shrink: 0;
  display: flex; align-items: center;
}
.progress-fill {
  height: 100%; background: linear-gradient(90deg, #409eff, #67c23a);
  transition: width .3s ease;
}
.progress-text {
  position: absolute; width: 100%; text-align: center; font-size: 12px; color: #303133;
}
.overview-bar {
  display: flex; flex-wrap: wrap; gap: 8px;
  padding: 8px 10px 0; flex-shrink: 0;
}
.overview-pill {
  display: inline-flex; align-items: center; min-height: 28px; padding: 0 10px;
  background: rgba(255,255,255,0.86); border: 1px solid #d8e0ea; border-radius: 999px;
  box-shadow: 0 4px 10px rgba(31, 45, 61, 0.05); font-size: 12px; color: #556273;
}
.overview-pill.is-ok { color: #2f8f51; border-color: #b9dfc5; background: rgba(237, 250, 242, 0.96); }
/* ---- Tab 切换栏 ---- */
.tab-bar {
  display: flex; gap: 2px; padding: 0 10px; flex-shrink: 0;
}
.tab-btn {
  padding: 7px 20px; border: 1px solid #d8e0ea; background: rgba(255,255,255,0.7);
  border-radius: 8px 8px 0 0; cursor: pointer; font-size: 13px; color: #606266;
  transition: all .15s; border-bottom: none;
}
.tab-btn.active {
  background: rgba(255,255,255,0.95); color: #409eff; font-weight: 600;
  border-color: #d8e0ea; box-shadow: 0 -2px 8px rgba(64,158,255,0.08);
}
.tab-btn:hover:not(.active) { color: #303133; background: rgba(255,255,255,0.88); }
/* 上传阶段不确定进度条动画 */
.progress-indeterminate {
  height: 100%; width: 30%; background: linear-gradient(90deg, #409eff, #67c23a);
  animation: progress-slide 1.5s ease-in-out infinite; border-radius: 2px;
}
@keyframes progress-slide {
  0% { margin-left: -30%; }
  100% { margin-left: 100%; }
}
@media (max-width: 900px) {
  .workspace { flex-direction: column; padding: 8px; }
  .pane-left, .pane-right { width: 100% !important; min-width: 0; min-height: 280px; }
  .splitter { display: none; }
}
</style>
