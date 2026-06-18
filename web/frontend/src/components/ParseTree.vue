<script>
import { h, ref } from 'vue'

export default {
  name: 'ParseTree',
  props: { message: Object },
  setup(props) {
    return () => {
      if (!props.message) return h('div', { class: 'tree-empty' }, '点击左侧行查看解析详情')
      if (!props.message.parsed) return h('div', { class: 'tree-empty tree-fail' }, '该消息无法解析（类型未注册或数据异常）')
      const hdr = props.message
      return h('div', { class: 'tree-panel' }, [
        h('div', { class: 'tree-info' }, [
          h('span', null, `${hdr.service_id} / ${hdr.method_id}`),
          h('span', null, `· ${hdr.message_kind}`),
          h('span', null, `· ${hdr.payload_length} bytes`),
        ]),
        h('div', { class: 'tree-scroll' }, [
          h(TreeNode, { node: props.message.parsed, key: 'root' }),
        ]),
      ])
    }
  },
}

// 递归树节点 — 可折叠
const TreeNode = {
  name: 'TreeNode',
  props: { node: Object },
  setup(p) {
    const open = ref(true)
    // 用 kind 字段区分容器/叶子（由后端 to_dict() 保证）
    const isContainer = p.node.kind === 'container'
    const ch = p.node.children || []
    return () => {
      if (isContainer) {
        const hasKids = ch.length > 0
        return h('div', { class: 'tn' }, [
          h('div', { class: 'tn-bar', onClick: () => { open.value = !open.value } }, [
            h('span', { class: 'tn-arrow' }, open.value ? '▾' : '▸'),
            h('span', { class: 'tn-name' }, p.node.name),
            h('span', { class: 'tn-meta' }, `(${p.node.type}, ${p.node.byte_size}B @${p.node.offset})`),
          ]),
          open.value && hasKids ? h('div', { class: 'tn-children' },
            ch.map((c, i) => h(TreeNode, { node: c, key: `${c.name}-${c.offset}-${i}` }))
          ) : null,
        ])
      }
      // 叶节点
      return h('div', { class: 'tn tn-leaf' }, [
        h('span', { class: 'tn-bullet' }, '·'),
        h('span', { class: 'tn-key' }, p.node.name),
        h('span', { class: 'tn-eq' }, '='),
        h('span', { class: 'tn-val' }, _formatVal(p.node.value)),
        h('span', { class: 'tn-meta' }, `(${p.node.type}, ${p.node.byte_size}B @${p.node.offset})`),
        p.node.hex ? h('span', { class: 'tn-hex' }, `[${p.node.hex}]`) : null,
      ])
    }
  },
}

function _formatVal(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return String(v)
}
</script>

<style>
.tree-panel { display: flex; flex-direction: column; height: 100%; }
.tree-info {
  padding: 8px 12px; font-size: 13px; color: #606266; background: #f5f7fa;
  border-bottom: 1px solid #ebeef5; flex-shrink: 0; display: flex; gap: 10px;
}
.tree-scroll { flex: 1; overflow: auto; padding: 8px 0; }
.tree-empty { color: #909399; text-align: center; padding: 60px 0; font-size: 15px; }
.tree-fail { color: #f56c6c; }
.tn { font-family: 'Consolas','Courier New',monospace; font-size: 14px; }
.tn-bar {
  display: flex; align-items: baseline; gap: 5px; padding: 3px 8px;
  cursor: pointer; user-select: none; border-radius: 3px;
}
.tn-bar:hover { background: #f0f7ff; }
.tn-arrow { color: #409eff; font-size: 12px; width: 16px; flex-shrink: 0; }
.tn-name { color: #303133; font-weight: 600; }
.tn-meta { color: #909399; font-size: 12px; font-weight: 400; }
.tn-children { padding-left: 22px; }
.tn-leaf { display: flex; align-items: baseline; gap: 6px; padding: 3px 8px 3px 24px; flex-wrap: wrap; }
.tn-bullet { color: #c0c4cc; font-size: 12px; }
.tn-key { color: #303133; font-size: 14px; }
.tn-eq { color: #c0c4cc; font-size: 14px; }
.tn-val { color: #409eff; font-weight: 600; font-size: 14px; }
.tn-hex { color: #c0c4cc; font-size: 12px; margin-left: 8px; word-break: break-all; }
</style>
