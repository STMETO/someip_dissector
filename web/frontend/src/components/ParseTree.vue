<script>
import { computed, h, ref } from 'vue'

export default {
  name: 'ParseTree',
  props: { message: Object },
  setup(props) {
    return () => {
      if (!props.message) {
        return h('div', { class: 'tree-empty' }, [
          h('div', { class: 'tree-empty-mark' }, 'SOME/IP'),
          h('div', { class: 'tree-empty-title' }, 'Select a packet'),
          h('div', { class: 'tree-empty-subtitle' }, 'Raw protocol fields and decoded payload will appear here.'),
        ])
      }

      const msg = props.message
      const statusChip = _statusChip(msg.parse_status)
      const sections = []

      if (msg.raw_view) {
        sections.push(h(TreeSection, {
          title: 'Raw Protocol Tree',
          subtitle: 'SOME/IP header, service discovery, payload bytes',
          node: msg.raw_view,
          tone: 'raw',
          key: 'raw-root',
        }))
      }

      if (msg.parsed && msg.parse_status === 'ok') {
        sections.push(h(TreeSection, {
          title: 'Decoded Payload',
          subtitle: 'Payload deserialized with ARXML type definitions',
          node: msg.parsed,
          tone: 'decoded',
          key: 'parsed-root',
        }))
      }

      return h('div', { class: 'tree-panel' }, [
        h('header', { class: 'tree-header' }, [
          h('div', { class: 'packet-title' }, [
            h('span', { class: 'packet-id mono' }, `${msg.service_id} / ${msg.method_id}`),
            h('span', { class: 'packet-kind' }, msg.message_kind || 'SOME/IP'),
          ]),
          h('div', { class: 'packet-facts' }, [
            h('span', { class: 'fact' }, msg.transport || '-'),
            h('span', { class: 'fact' }, `${msg.payload_length || 0}B payload`),
            statusChip ? h('span', { class: `fact ${statusChip.cls}` }, statusChip.label) : null,
          ]),
        ]),
        h('div', { class: 'tree-scroll' }, sections),
      ])
    }
  },
}

const TreeSection = {
  name: 'TreeSection',
  props: { title: String, subtitle: String, node: Object, tone: String },
  setup(props) {
    return () => h('section', { class: ['tree-section', `tone-${props.tone || 'raw'}`] }, [
      h('header', { class: 'section-head' }, [
        h('div', null, [
          h('div', { class: 'section-title' }, props.title),
          h('div', { class: 'section-subtitle' }, props.subtitle),
        ]),
        h('span', { class: 'section-size' }, `${props.node?.byte_size || 0} bytes`),
      ]),
      h(TreeNode, { node: props.node, depth: 0 }),
    ])
  },
}

const TreeNode = {
  name: 'TreeNode',
  props: { node: Object, depth: { type: Number, default: 0 } },
  setup(props) {
    const open = ref(props.depth <= 1)
    const children = computed(() => props.node?.children || [])
    const hasKids = computed(() => children.value.length > 0)
    const rowStyle = computed(() => ({ paddingLeft: `${14 + props.depth * 18}px` }))

    return () => {
      if (hasKids.value) {
        const meta = props.node.meta_kind || ''
        return h('div', { class: 'tn' }, [
          h('div', { class: ['branch-row', open.value ? 'is-open' : ''], style: rowStyle.value }, [
            h('button', {
              class: 'branch-toggle',
              type: 'button',
              title: open.value ? 'Collapse' : 'Expand',
              onClick: () => { open.value = !open.value },
            }, open.value ? '-' : '+'),
            h('div', { class: 'branch-main' }, [
              h('span', { class: 'branch-name' }, props.node.name),
              h('span', { class: 'branch-type' }, props.node.type || 'container'),
              meta ? h('span', { class: `node-badge node-badge-${meta}` }, _metaLabel(meta)) : null,
            ]),
            h('span', { class: 'branch-meta' }, `${props.node.byte_size || 0}B @ ${props.node.offset || 0}`),
          ]),
          open.value ? h('div', { class: 'branch-children' }, children.value.map((child, idx) => h(TreeNode, {
            node: child,
            depth: props.depth + 1,
            key: `${child.name}-${child.offset}-${idx}`,
          }))) : null,
        ])
      }

      const value = _valueParts(props.node)
      return h('div', { class: 'tn leaf-row', style: rowStyle.value }, [
        h('div', { class: 'leaf-key' }, props.node.name),
        h('div', { class: 'leaf-body' }, [
          h('div', { class: 'leaf-value' }, value.main),
          value.meaning ? h('div', { class: 'leaf-meaning' }, [
            h('span', { class: 'meta-label' }, 'meaning'),
            h('span', { class: 'meaning-text' }, value.meaning),
          ]) : null,
        ]),
        h('div', { class: 'leaf-meta' }, [
          h('span', null, ['len ', h('strong', null, `${props.node.byte_size || 0}B`)]),
          h('span', null, ['offset ', h('strong', null, `${props.node.offset || 0}B`)]),
        ]),
        props.node.hex ? h('code', { class: 'leaf-raw', title: props.node.hex }, props.node.hex) : null,
      ])
    }
  },
}

function _valueParts(node) {
  const value = node.value
  if (_isHexDecValue(value)) {
    return {
      main: [
        h('span', { class: 'value-chip hex-chip' }, ['hex ', h('strong', null, value.hex || '')]),
        h('span', { class: 'value-chip dec-chip' }, ['dec ', h('strong', null, String(value.dec ?? 0))]),
      ],
      meaning: value.meaning || '',
    }
  }
  return {
    main: h('span', { class: 'plain-value' }, _formatVal(value)),
    meaning: '',
  }
}

function _isHexDecValue(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.prototype.hasOwnProperty.call(value, 'hex')
    && Object.prototype.hasOwnProperty.call(value, 'dec')
}

function _formatVal(value) {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function _statusChip(st) {
  if (st === 'sd') return { label: 'SOME/IP-SD', cls: 'status-sd' }
  if (st === 'unresolved') return { label: 'Unresolved', cls: 'status-unresolved' }
  if (st === 'ok') return { label: 'Decoded', cls: 'status-ok' }
  return null
}

function _metaLabel(meta) {
  if (meta === 'raw') return 'RAW'
  if (meta === 'sd') return 'SD'
  if (meta === 'unresolved') return 'UNRESOLVED'
  return meta.toUpperCase()
}
</script>

<style>
.tree-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #0f172a;
  color: #dbe7f5;
}
.tree-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 16px;
  background: #111827;
  border-bottom: 1px solid #243244;
}
.packet-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.packet-id { font-size: 15px; font-weight: 850; color: #f8fafc; }
.packet-kind {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  border-radius: 5px;
  background: #1e293b;
  color: #93c5fd;
  font-size: 12px;
  font-weight: 800;
}
.packet-facts { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.fact {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 8px;
  border: 1px solid #334155;
  border-radius: 5px;
  color: #cbd5e1;
  font-size: 12px;
  font-weight: 750;
  background: #0f172a;
}
.status-ok { color: #86efac; border-color: #166534; background: #052e1a; }
.status-sd { color: #fde68a; border-color: #92400e; background: #342006; }
.status-unresolved { color: #fca5a5; border-color: #991b1b; background: #3b0a0a; }
.tree-scroll {
  flex: 1;
  overflow: auto;
  padding: 14px;
  background: #0b1120;
}
.tree-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  color: #94a3b8;
  background: #0b1120;
}
.tree-empty-mark {
  letter-spacing: .16em;
  color: #60a5fa;
  font-weight: 900;
  font-size: 12px;
}
.tree-empty-title { color: #f8fafc; font-size: 18px; font-weight: 850; }
.tree-empty-subtitle { font-size: 13px; }
.tree-section {
  overflow: hidden;
  border: 1px solid #26364a;
  border-radius: 8px;
  background: #111827;
  margin-bottom: 12px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  background: #162033;
  border-bottom: 1px solid #26364a;
}
.section-title { font-size: 14px; font-weight: 900; color: #f8fafc; }
.section-subtitle { margin-top: 2px; color: #94a3b8; font-size: 12px; }
.section-size {
  flex-shrink: 0;
  border: 1px solid #334155;
  border-radius: 5px;
  color: #cbd5e1;
  background: #0f172a;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 800;
}
.tn { font-family: Consolas, 'Courier New', monospace; font-size: 13px; }
.branch-row {
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding-top: 6px;
  padding-bottom: 6px;
  padding-right: 12px;
  border-bottom: 1px solid rgba(51, 65, 85, .7);
  background: #111827;
}
.branch-row:hover, .leaf-row:hover { background: #16243a; }
.branch-toggle {
  width: 20px;
  height: 20px;
  border: 1px solid #475569;
  border-radius: 4px;
  background: #0f172a;
  color: #bfdbfe;
  cursor: pointer;
  font-weight: 900;
  line-height: 1;
  flex-shrink: 0;
}
.branch-toggle:hover { border-color: #60a5fa; color: #ffffff; }
.branch-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.branch-name { color: #f8fafc; font-weight: 850; }
.branch-type {
  color: #a5b4fc;
  background: #1e1b4b;
  border: 1px solid #3730a3;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  font-weight: 750;
}
.branch-meta { margin-left: auto; color: #94a3b8; font-size: 12px; }
.branch-children { border-left: 1px solid #334155; margin-left: 23px; }
.node-badge {
  color: #cbd5e1;
  background: #0f172a;
  border: 1px solid #475569;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 900;
}
.node-badge-raw { color: #bae6fd; border-color: #0369a1; background: #082f49; }
.node-badge-sd { color: #fde68a; border-color: #92400e; background: #342006; }
.node-badge-unresolved { color: #fca5a5; border-color: #991b1b; background: #3b0a0a; }
.leaf-row {
  display: grid;
  grid-template-columns: minmax(145px, 220px) minmax(260px, 1fr) minmax(155px, auto) minmax(80px, 22%);
  align-items: center;
  column-gap: 12px;
  min-height: 38px;
  padding-top: 7px;
  padding-bottom: 7px;
  padding-right: 12px;
  border-bottom: 1px solid rgba(51, 65, 85, .55);
  background: #0f172a;
}
.leaf-key {
  color: #f8fafc;
  font-weight: 900;
  letter-spacing: 0;
}
.leaf-body { display: flex; align-items: center; gap: 10px; min-width: 0; }
.leaf-value { display: inline-flex; align-items: center; gap: 7px; flex-wrap: wrap; min-width: 0; }
.value-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 24px;
  padding: 0 8px;
  border-radius: 5px;
  font-size: 12px;
  color: #94a3b8;
  background: #1e293b;
  border: 1px solid #334155;
}
.value-chip strong { color: #f8fafc; font-weight: 900; }
.hex-chip { border-color: #1d4ed8; background: #172554; }
.dec-chip { border-color: #0f766e; background: #042f2e; }
.plain-value {
  color: #f8fafc;
  font-weight: 800;
  word-break: break-word;
}
.leaf-meaning {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid #7c3aed;
  border-radius: 5px;
  background: #2e1065;
  white-space: nowrap;
}
.meta-label { color: #c4b5fd; font-size: 11px; font-weight: 900; text-transform: uppercase; }
.meaning-text { color: #f5f3ff; font-weight: 900; }
.leaf-meta {
  display: inline-flex;
  justify-content: flex-end;
  gap: 8px;
  color: #94a3b8;
  font-size: 12px;
  white-space: nowrap;
}
.leaf-meta strong { color: #e2e8f0; }
.leaf-raw {
  justify-self: stretch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #64748b;
  background: #020617;
  border: 1px solid #1e293b;
  border-radius: 4px;
  padding: 4px 6px;
  user-select: text;
}
@media (max-width: 1100px) {
  .leaf-row { grid-template-columns: minmax(130px, 180px) minmax(260px, 1fr); row-gap: 6px; }
  .leaf-meta { justify-content: flex-start; }
  .leaf-raw { grid-column: 2; }
}
@media (max-width: 760px) {
  .tree-header { align-items: flex-start; flex-direction: column; }
  .leaf-row { grid-template-columns: 1fr; }
  .leaf-raw { grid-column: auto; }
  .branch-meta { margin-left: 0; }
  .branch-row { flex-wrap: wrap; }
}
</style>
