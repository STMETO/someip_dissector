<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  messages: Array, loading: Boolean, selectedIndex: Number, searchText: String,
})
const emit = defineEmits(['select', 'update:searchText'])

const currentPage = ref(1)
const pageSize = 100

const filtered = computed(() => {
  if (!props.searchText) return props.messages || []
  const q = props.searchText.toLowerCase()
  return (props.messages || []).filter(m =>
    String(m.index).includes(q) ||
    String(m.frame_index).includes(q) ||
    String(m.payload_length).includes(q) ||
    String(m.service_id).toLowerCase().includes(q) ||
    String(m.method_id).toLowerCase().includes(q) ||
    String(m.message_kind).toLowerCase().includes(q)
  )
})

const paged = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filtered.value.slice(start, start + pageSize)
})

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))

watch(() => props.messages, () => { currentPage.value = 1 })
watch(filtered, () => { currentPage.value = 1 })

function goPage(v) {
  const n = parseInt(v, 10)
  if (n >= 1 && n <= totalPages.value) currentPage.value = n
}
</script>

<template>
  <div class="msg-panel">
    <div class="msg-header">
      <span>消息列表 ({{ filtered.length }} 条)
        <template v-if="!loading && props.messages?.length">
          · 已解析 {{ props.messages.filter(m => m.parse_status === 'ok').length }}
        </template>
      </span>
      <input class="search-input" placeholder="搜索序号/帧号/长度/ID/类型..."
             :value="searchText"
             @input="emit('update:searchText', $event.target.value)">
    </div>
    <div class="msg-table-wrap">
      <table class="msg-table">
        <thead>
          <tr>
            <th style="width:45px">序号</th>
            <th style="width:45px">帧号</th>
            <th style="width:80px">Service ID</th>
            <th style="width:100px">Method/Event</th>
            <th style="width:70px">msg_type</th>
            <th style="width:45px">长度</th>
            <th style="width:55px">状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading"><td colspan="7" class="empty">解析中...</td></tr>
          <tr v-else-if="!paged.length"><td colspan="7" class="empty">无匹配结果</td></tr>
          <tr v-for="m in paged" :key="m.index"
              :class="{ selected: m.index === selectedIndex }"
              class="msg-row"
              @click="emit('select', m)">
            <td class="mono">{{ m.index }}</td>
            <td class="mono">{{ m.frame_index }}</td>
            <td class="mono">{{ m.service_id }}</td>
            <td class="mono">{{ m.method_id }}</td>
            <td class="mono">{{ m.message_kind }}</td>
            <td class="mono" style="text-align:right">{{ m.payload_length }}</td>
            <td>
              <span class="tag" :class="m.parse_status === 'ok' ? 'tag-ok' : 'tag-fail'">
                {{ m.parse_status === 'ok' ? '已解析' : '未解析' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="msg-footer" v-if="filtered.length > pageSize">
      <button :disabled="currentPage <= 1" @click="currentPage--">上一页</button>
      <input class="page-num" :value="currentPage" @change="goPage($event.target.value)" style="width:40px;text-align:center">
      <span>/ {{ totalPages }}</span>
      <button :disabled="currentPage >= totalPages" @click="currentPage++">下一页</button>
    </div>
  </div>
</template>

<style>
.msg-panel { display: flex; flex-direction: column; height: 100%; }
.msg-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 10px; background: #f5f7fa; border-bottom: 1px solid #ebeef5;
  font-size: 13px; flex-shrink: 0;
}
.search-input {
  width: 200px; padding: 3px 8px; border: 1px solid #dcdfe6; border-radius: 3px;
  font-size: 12px; outline: none;
}
.msg-table-wrap { flex: 1; overflow: auto; }
.msg-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.msg-table th {
  position: sticky; top: 0; background: #f5f7fa; padding: 4px 6px;
  text-align: left; border-bottom: 1px solid #ebeef5; font-weight: 600; z-index: 1;
}
.msg-table td { padding: 3px 6px; border-bottom: 1px solid #f2f2f2; }
.msg-row { cursor: pointer; }
.msg-row:hover { background: #f0f7ff; }
.msg-row.selected { background: #ecf5ff; }
.mono { font-family: 'Consolas','Courier New',monospace; }
.empty { text-align: center; color: #999; padding: 20px; }
.tag { font-size: 11px; padding: 1px 6px; border-radius: 3px; }
.tag-ok { background: #e1f3d8; color: #67c23a; }
.tag-fail { background: #fef0f0; color: #f56c6c; }
.msg-footer {
  display: flex; justify-content: center; align-items: center; gap: 6px;
  padding: 6px; border-top: 1px solid #ebeef5; font-size: 12px; flex-shrink: 0;
}
.msg-footer button { padding: 2px 10px; cursor: pointer; }
.page-num { border: 1px solid #dcdfe6; border-radius: 2px; padding: 2px 4px; font-size: 12px; }
</style>
