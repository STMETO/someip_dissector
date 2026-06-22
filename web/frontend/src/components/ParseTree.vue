<script>
import { computed, h, ref } from 'vue'

export default {
  name: 'ParseTree',
  props: { message: Object },
  setup(props) {
    return () => {
      if (!props.message) return h('div', { class: 'tree-empty' }, '点击左侧行查看解析详情')
      const hdr = props.message
      const st = hdr.parse_status
      const statusLabel = st === 'sd' ? 'SOME/IP-SD' : st === 'unresolved' ? '未解析' : ''
      return h('div', { class: 'tree-panel' }, [
        h('div', { class: 'tree-info' }, [
          h('span', { class: 'tree-info-chip mono' }, `${hdr.service_id} / ${hdr.method_id}`),
          h('span', { class: 'tree-info-chip' }, hdr.message_kind),
          h('span', { class: 'tree-info-chip' }, `${hdr.payload_length} bytes`),
          statusLabel ? h('span', { class: `tree-info-chip tree-status-${st}` }, statusLabel) : null,
        ]),
        h('div', { class: 'tree-scroll' }, [
          h(TreeNode, { node: props.message.parsed, depth: 0, key: 'root' }),
        ]),
      ])
    }
  },
}

// 递归树节点
const TreeNode = {
  name: 'TreeNode',
  props: { node: Object, depth: { type: Number, default: 0 } },
  setup(p) {
    const isRoot = p.depth === 0
    // 根节点默认展开，子节点默认收起
    const open = ref(isRoot)
    const ch = computed(() => p.node.children || [])
    const hasKids = computed(() => ch.value.length > 0)
    const meta = p.node.meta_kind || ''
    const rowStyle = computed(() => ({
      paddingLeft: `${10 + p.depth * 20}px`,
    }))

    return () => {
      // ---- 容器节点 ----
      if (hasKids.value) {
        const rowCls = ['tn-row', 'tn-container-row', open.value ? 'is-open' : '', isRoot ? 'is-root' : '']
        return h('div', { class: 'tn' }, [
          h('div', { class: rowCls, style: rowStyle.value }, [
            h('button', {
              class: 'tn-toggle',
              type: 'button',
              onClick: () => { open.value = !open.value },
            }, open.value ? '▾' : '▸'),
            meta ? h('span', { class: `tn-badge tn-badge-${meta}` }, meta === 'sd' ? 'SOME/IP-SD' : 'UNRESOLVED') : null,
            h('span', { class: 'tn-label' }, p.node.name),
            h('span', { class: 'tn-type', title: p.node.type || '' }, p.node.type || '—'),
            h('span', { class: 'tn-meta' }, `${p.node.byte_size}B @${p.node.offset}`),
          ]),
          open.value ? h('div', { class: 'tn-children' },
            ch.value.map((c, i) => h(TreeNode, {
              node: c,
              depth: p.depth + 1,
              key: `${c.name}-${c.offset}-${i}`,
            }))
          ) : null,
        ])
      }

      // ---- 叶子节点 ----
      return h('div', { class: 'tn tn-leaf' }, [
        h('div', { class: ['tn-row', 'tn-leaf-row'], style: rowStyle.value }, [
          h('span', { class: 'tn-toggle tn-toggle-placeholder', 'aria-hidden': 'true' }, ''),
          h('span', { class: 'tn-label' }, p.node.name),
          h('span', { class: 'tn-val' }, _formatVal(p.node.value)),
          h('span', { class: 'tn-type', title: p.node.type || '' }, p.node.type || '—'),
          h('span', { class: 'tn-meta' }, `${p.node.byte_size}B @${p.node.offset}`),
          p.node.hex ? h('span', { class: 'tn-hex', title: p.node.hex }, `[${p.node.hex}]`) : null,
        ]),
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
  padding: 10px 12px; font-size: 13px; color: #606266; background: linear-gradient(180deg, #f9fbfd, #f1f5f9);
  border-bottom: 1px solid #e5ebf2; flex-shrink: 0; display: flex; gap: 10px; flex-wrap: wrap;
}
.tree-info-chip {
  display: inline-flex; align-items: center; min-height: 26px; padding: 0 10px;
  border-radius: 999px; background: #fff; border: 1px solid #dde5ef; color: #51606f;
}
.tree-status-sd { color: #e6a23c; border-color: #f5dab1; background: #fef8f0; font-weight: 600; }
.tree-status-unresolved { color: #f56c6c; border-color: #fbc4c4; background: #fef0f0; font-weight: 600; }
.tree-scroll { flex: 1; overflow: auto; padding: 10px 8px 18px; background: linear-gradient(180deg, #fff, #fafcff); }
.tree-empty { color: #909399; text-align: center; padding: 60px 0; font-size: 15px; }
.tn { font-family: 'Consolas','Courier New',monospace; font-size: 14px; position: relative; }
.tn-row {
  display: flex; align-items: center; gap: 8px; padding-top: 3px; padding-bottom: 3px;
  padding-right: 8px; border-radius: 8px; flex-wrap: wrap; position: relative;
}
.tn-row:hover { background: #f0f7ff; }
.tn-toggle {
  width: 17px; height: 17px; padding: 0; border: 1px solid #9fc5f2; background: linear-gradient(180deg, #f5faff, #dfeeff); cursor: pointer;
  color: #1f6fd6; font-size: 11px; font-weight: 800; line-height: 1; flex-shrink: 0; user-select: none; border-radius: 4px;
  display: inline-flex; align-items: center; justify-content: center; box-shadow: 0 2px 6px rgba(47, 128, 237, 0.12);
  transform: translateY(1px);
}
.tn-toggle:hover { background: linear-gradient(180deg, #ebf5ff, #d3e8ff); border-color: #6da7ea; }
.tn-toggle-placeholder {
  cursor: default; color: transparent; border-color: transparent; background: transparent; box-shadow: none;
}
.tn-label { color: #303133; font-weight: 600; }
.tn-val { color: #409eff; font-weight: 600; font-size: 14px; }
.tn-type {
  color: #606266; font-size: 12px; padding: 1px 6px; border-radius: 10px;
  background: #f4f4f5; border: 1px solid #e4e7ed;
}
.tn-meta { color: #909399; font-size: 12px; font-weight: 400; }
.tn-children {
  padding-left: 14px; margin-left: 14px; border-left: 2px solid #d8e6f5;
}
.tn-children .tn-row::before {
  content: ''; position: absolute; left: -14px; top: 16px; width: 12px;
  border-top: 2px solid #d8e6f5;
}
.tn-hex {
  color: #c0c4cc; font-size: 12px; margin-left: 8px; word-break: break-all;
  user-select: text;
}
/* ---- 状态徽标 ---- */
.tn-badge {
  display: inline-flex; align-items: center; min-height: 20px; padding: 0 7px;
  border-radius: 4px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
  flex-shrink: 0;
}
.tn-badge-sd { color: #b88230; background: #fef6ed; border: 1px solid #f0d199; }
.tn-badge-unresolved { color: #c45656; background: #fef0f0; border: 1px solid #f1b6b6; }
</style>
