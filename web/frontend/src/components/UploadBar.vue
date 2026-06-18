<script setup>
import { ref, computed, watch } from 'vue'
import { uploadFiles, exportUrl } from '../api'

const emit = defineEmits(['parsed', 'update:uploading'])
const props = defineProps({ loading: Boolean, sessionId: String, hasExport: Boolean })

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
          @drop.prevent="onDrop">
    <div class="toolbar-top">
      <span class="brand">SOME/IP Dissector</span>
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
          <a v-if="hasExport" :href="exportUrl(sessionId, 'pcap_output.json')" class="lnk">↓ PCAP JSON</a>
          <a v-if="hasExport" :href="exportUrl(sessionId, 'arxml_output.json')" class="lnk">↓ ARXML JSON</a>
        </template>
      </div>
    </div>
    <div class="toolbar-hint" v-if="!sessionId">
      拖拽 pcap + arxml 文件到此处，或点击按钮选择文件
    </div>
  </header>
</template>

<style>
.toolbar {
  flex-shrink: 0; background: #f5f7fa; border-bottom: 1px solid #dcdfe6;
  padding: 10px 20px; user-select: none;
}
.toolbar-top {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.brand { font-size: 17px; font-weight: 700; color: #303133; }
.toolbar-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pick-btn {
  position: relative; padding: 7px 16px; border: 1px dashed #c0c4cc;
  border-radius: 4px; cursor: pointer; font-size: 13px; color: #606266;
  background: #fff; transition: border-color .2s;
}
.pick-btn:hover { border-color: #409eff; }
.pick-btn.active { border-style: solid; border-color: #409eff; color: #303133; }
.pick-btn input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.check-label { font-size: 13px; display: flex; align-items: center; gap: 4px; cursor: pointer; }
.btn-go {
  padding: 7px 24px; background: #409eff; color: #fff; border: none;
  border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: 500;
}
.btn-go:disabled { background: #a0cfff; cursor: not-allowed; }
.lnk { font-size: 12px; color: #409eff; text-decoration: none; margin-left: 4px; }
.toolbar-hint {
  margin-top: 6px; font-size: 12px; color: #909399;
}
</style>
