<script setup>
import { ref, computed, watch } from 'vue'
import { uploadFiles, exportUrl } from '../api'

const emit = defineEmits(['parsed', 'update:uploading', 'update:theme'])
const props = defineProps({
  loading: Boolean,
  sessionId: String,
  hasExport: Boolean,
  theme: { type: String, default: 'light' },
})

const pcapFile = ref(null)
const arxmlFile = ref(null)
const keepTemp = ref(false)
const submitting = ref(false)
const dragOver = ref(false)

watch(submitting, (val) => emit('update:uploading', val))

const canSubmit = computed(() => pcapFile.value && arxmlFile.value && !props.loading && !submitting.value)

function handlePcap(e) { pcapFile.value = e.target.files[0] || null }
function handleArxml(e) { arxmlFile.value = e.target.files[0] || null }

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const res = await uploadFiles(pcapFile.value, arxmlFile.value, keepTemp.value)
    emit('parsed', res)
  } catch (e) {
    alert('解析失败: ' + (e.response?.data?.detail || e.message))
  } finally { submitting.value = false }
}

function onDrop(e) {
  dragOver.value = false
  const files = e.dataTransfer?.files || []
  for (const f of files) {
    const name = f.name.toLowerCase()
    if (name.endsWith('.pcap') || name.endsWith('.pcapng') || name.endsWith('.cap'))
      pcapFile.value = f
    else if (name.endsWith('.arxml') || name.endsWith('.xml'))
      arxmlFile.value = f
  }
}
</script>

<template>
  <header class="toolbar"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
          :class="{ 'toolbar-dragover': dragOver }">
    <div class="toolbar-top">
      <div class="brand-block">
        <span class="brand">SOME/IP Dissector</span>
        <span class="brand-subtitle">PCAP / ARXML protocol analysis workbench</span>
      </div>
      <div class="toolbar-actions">
        <label class="pick-btn" :class="{ active: pcapFile }">
          {{ pcapFile ? pcapFile.name : '选择 PCAP' }}
          <input type="file" accept=".pcap,.pcapng,.cap" @change="handlePcap">
        </label>
        <label class="pick-btn" :class="{ active: arxmlFile }">
          {{ arxmlFile ? arxmlFile.name : '选择 ARXML' }}
          <input type="file" accept=".arxml,.xml" @change="handleArxml">
        </label>
        <label class="check-label"><input type="checkbox" v-model="keepTemp"> 保留中间JSON</label>
        <button class="btn-go" :disabled="!canSubmit" @click="submit">
          {{ submitting ? '解析中...' : '开始解析' }}
        </button>
        <template v-if="sessionId">
          <a v-if="hasExport" :href="exportUrl(sessionId, 'pcap_output.json')" class="lnk">PCAP JSON</a>
          <a v-if="hasExport" :href="exportUrl(sessionId, 'arxml_output.json')" class="lnk">ARXML JSON</a>
          <a v-if="hasExport" :href="exportUrl(sessionId, 'deserialized_output.json')" class="lnk">反序列化 JSON</a>
        </template>
        <div class="theme-switch" role="group" aria-label="Color theme">
          <button type="button" :aria-pressed="theme === 'light'" :class="{ active: theme === 'light' }" @click="emit('update:theme', 'light')">Light</button>
          <button type="button" :aria-pressed="theme === 'dark'" :class="{ active: theme === 'dark' }" @click="emit('update:theme', 'dark')">Dark</button>
        </div>
      </div>
    </div>
    <div class="toolbar-hint" v-if="!sessionId">
      拖拽 pcap + arxml 文件到此处，或点击按钮选择文件。建议先上传同一版本的协议定义与抓包，避免类型未注册。
    </div>
  </header>
</template>

<style>
.toolbar {
  flex-shrink: 0;
  background: var(--surface-raised);
  border-bottom: 1px solid var(--border);
  padding: 12px 16px 10px;
  user-select: none;
  box-shadow: 0 1px 0 rgba(0, 0, 0, .02);
}
.toolbar-dragover {
  background: var(--accent-soft);
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.toolbar-top {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  justify-content: space-between;
}
.brand-block { display: flex; flex-direction: column; gap: 2px; }
.brand {
  font-size: 18px;
  font-weight: 900;
  color: var(--text-primary);
  letter-spacing: 0;
}
.brand-subtitle {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 650;
}
.toolbar-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pick-btn {
  position: relative;
  max-width: 220px;
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--surface-subtle);
  transition: border-color .15s, background .15s, color .15s;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.pick-btn:hover { border-color: var(--accent-border); color: var(--text-primary); background: var(--surface-hover); }
.pick-btn.active { border-color: var(--accent-border); color: var(--accent); background: var(--accent-soft); }
.pick-btn input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.check-label {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
}
.check-label input { width: 14px; height: 14px; accent-color: var(--accent); }
.btn-go {
  min-height: 34px;
  padding: 0 18px;
  background: var(--accent);
  color: var(--accent-contrast);
  border: 1px solid var(--accent);
  border-radius: var(--radius-control);
  cursor: pointer;
  font-size: 13px;
  font-weight: 900;
  box-shadow: none;
}
.btn-go:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn-go:disabled {
  background: var(--surface-muted);
  border-color: var(--border);
  color: var(--text-tertiary);
  cursor: not-allowed;
  box-shadow: none;
}
.lnk {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
  padding: 0 9px;
  border-radius: var(--radius-control);
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  font-weight: 800;
}
.lnk:hover { background: var(--surface-selected); }
.toolbar-hint {
  margin-top: 9px;
  font-size: 12px;
  color: var(--text-tertiary);
}
.theme-switch {
  display: inline-grid;
  grid-template-columns: 1fr 1fr;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--surface-muted);
}
.theme-switch button {
  min-width: 48px;
  min-height: 28px;
  padding: 0 8px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}
.theme-switch button:hover { color: var(--text-primary); }
.theme-switch button.active {
  color: var(--text-primary);
  background: var(--surface-raised);
  box-shadow: 0 1px 4px rgba(20, 24, 30, .12);
}
@media (max-width: 900px) {
  .toolbar-top { justify-content: flex-start; }
  .toolbar-actions { width: 100%; }
  .pick-btn { max-width: 100%; }
}
</style>
