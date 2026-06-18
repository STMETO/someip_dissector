<script setup>
import { ref, reactive, onUnmounted } from 'vue'
import UploadBar from './components/UploadBar.vue'
import MessageTable from './components/MessageTable.vue'
import ParseTree from './components/ParseTree.vue'
import { fetchMessages, fetchMessageDetail, deleteSession, exportUrl } from './api'

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

// 分割条位置 (左栏百分比)
const splitPercent = ref(60)
const dragging = ref(false)

function onDragStart(e) {
  dragging.value = true
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', onDragEnd)
}
function onDrag(e) {
  const pct = (e.clientX / window.innerWidth) * 100
  splitPercent.value = Math.max(20, Math.min(80, pct))
}
function onDragEnd() {
  dragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', onDragEnd)
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
    <div class="workspace" v-if="sessionId">
      <div class="pane pane-left" :style="{ width: splitPercent + '%' }">
        <MessageTable :messages="messages" :loading="loading"
                      :selectedIndex="selectedMsg?.index"
                      v-model:searchText="searchText"
                      @select="onSelect" />
      </div>
      <div class="splitter" @mousedown.prevent="onDragStart"></div>
      <div class="pane pane-right" :style="{ width: (100 - splitPercent) + '%' }">
        <ParseTree :message="selectedMsg" :key="selectedMsg?.index" />
      </div>
    </div>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; overflow: hidden; font-family: 'Segoe UI', sans-serif; }
.app-shell { display: flex; flex-direction: column; height: 100%; }
.workspace { flex: 1; display: flex; overflow: hidden; }
.pane { overflow: auto; display: flex; flex-direction: column; }
.pane-left { min-width: 200px; }
.pane-right { min-width: 250px; }
.splitter {
  width: 5px; cursor: col-resize; background: #dcdfe6;
  flex-shrink: 0; transition: background .2s;
}
.splitter:hover { background: #409eff; }
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
/* 上传阶段不确定进度条动画 */
.progress-indeterminate {
  height: 100%; width: 30%; background: linear-gradient(90deg, #409eff, #67c23a);
  animation: progress-slide 1.5s ease-in-out infinite; border-radius: 2px;
}
@keyframes progress-slide {
  0% { margin-left: -30%; }
  100% { margin-left: 100%; }
}
</style>
