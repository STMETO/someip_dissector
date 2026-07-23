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
            h('span', { class: 'fact' }, msg.message_type_name || msg.message_type || '-'),
            h('span', { class: 'fact', title: msg.timestamp_iso || '' }, _formatTimestamp(msg.timestamp_epoch)),
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
      const showLocation = props.node.show_location !== false
      return h('div', { class: 'tn leaf-row', style: rowStyle.value }, [
        h('div', { class: 'leaf-key' }, props.node.name),
        h('div', { class: 'leaf-body' }, [
          h('div', { class: 'leaf-value' }, value.main),
          value.meaning ? h('div', { class: 'leaf-meaning' }, [
            h('span', { class: 'meta-label' }, 'meaning'),
            h('span', { class: 'meaning-text' }, value.meaning),
          ]) : null,
        ]),
        showLocation ? h('div', { class: 'leaf-meta' }, [
          h('span', null, ['len ', h('strong', null, `${props.node.byte_size || 0}B`)]),
          h('span', null, ['offset ', h('strong', null, `${props.node.offset || 0}B`)]),
        ]) : null,
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

function _formatTimestamp(epoch) {
  const n = Number(epoch)
  if (!Number.isFinite(n) || n <= 0) return '-'
  const d = new Date(n * 1000)
  const pad = (v, len = 2) => String(v).padStart(len, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
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
  background: var(--surface);
  color: var(--text-primary);
}
.tree-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 16px;
  background: var(--surface-raised);
  border-bottom: 1px solid var(--border);
}
.packet-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.packet-id { font-size: 15px; font-weight: 850; color: var(--text-primary); }
.packet-kind {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 9px;
  border-radius: var(--radius-control);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
}
.packet-facts { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.fact {
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  padding: 0 8px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 750;
  background: var(--surface-subtle);
}
.status-ok { color: var(--success); border-color: var(--success-border); background: var(--success-soft); }
.status-sd { color: var(--warning); border-color: var(--warning-border); background: var(--warning-soft); }
.status-unresolved { color: var(--danger); border-color: var(--danger-border); background: var(--danger-soft); }
.tree-scroll {
  flex: 1;
  overflow: auto;
  padding: 14px;
  background: var(--canvas-deep);
}
.tree-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  text-align: center;
  color: var(--text-tertiary);
  background: var(--canvas-deep);
}
.tree-empty-mark {
  letter-spacing: .16em;
  color: var(--accent);
  font-weight: 900;
  font-size: 12px;
}
.tree-empty-title { color: var(--text-primary); font-size: 18px; font-weight: 850; }
.tree-empty-subtitle { font-size: 13px; }
.tree-section {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  margin-bottom: 12px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  background: var(--surface-muted);
  border-bottom: 1px solid var(--border);
}
.section-title { font-size: 14px; font-weight: 900; color: var(--text-primary); }
.section-subtitle { margin-top: 2px; color: var(--text-secondary); font-size: 12px; }
.section-size {
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  color: var(--text-secondary);
  background: var(--surface);
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 800;
}
.tn { font-family: var(--font-mono); font-size: 13px; font-variant-numeric: tabular-nums; }
.branch-row {
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding-top: 6px;
  padding-bottom: 6px;
  padding-right: 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.branch-row:hover, .leaf-row:hover { background: var(--surface-hover); }
.branch-toggle {
  width: 20px;
  height: 20px;
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  background: var(--surface-subtle);
  color: var(--accent);
  cursor: pointer;
  font-weight: 900;
  line-height: 1;
  flex-shrink: 0;
}
.branch-toggle:hover { border-color: var(--accent); color: var(--accent-hover); }
.branch-main { display: flex; align-items: center; gap: 8px; min-width: 0; }
.branch-name { color: var(--text-primary); font-weight: 850; }
.branch-type {
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  font-weight: 750;
}
.branch-meta { margin-left: auto; color: var(--text-tertiary); font-size: 12px; }
.branch-children { border-left: 1px solid var(--border); margin-left: 23px; }
.node-badge {
  color: var(--text-secondary);
  background: var(--surface-subtle);
  border: 1px solid var(--border-strong);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  font-weight: 900;
}
.node-badge-raw { color: var(--info); border-color: var(--info-border); background: var(--info-soft); }
.node-badge-sd { color: var(--warning); border-color: var(--warning-border); background: var(--warning-soft); }
.node-badge-unresolved { color: var(--danger); border-color: var(--danger-border); background: var(--danger-soft); }
.leaf-row {
  display: grid;
  grid-template-columns: minmax(145px, 220px) minmax(260px, 1fr) minmax(155px, auto);
  align-items: center;
  column-gap: 12px;
  min-height: 38px;
  padding-top: 7px;
  padding-bottom: 7px;
  padding-right: 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.leaf-key {
  color: var(--text-primary);
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
  border-radius: var(--radius-control);
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--surface-muted);
  border: 1px solid var(--border);
}
.value-chip strong { color: var(--text-primary); font-weight: 900; }
.hex-chip { border-color: var(--accent-border); background: var(--accent-soft); }
.dec-chip { border-color: var(--border-strong); background: var(--surface-subtle); }
.plain-value {
  color: var(--text-primary);
  font-weight: 800;
  word-break: break-word;
}
.leaf-meaning {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-control);
  background: var(--accent-soft);
  white-space: nowrap;
}
.meta-label { color: var(--accent); font-size: 11px; font-weight: 900; text-transform: uppercase; }
.meaning-text { color: var(--text-primary); font-weight: 900; }
.leaf-meta {
  display: inline-flex;
  justify-content: flex-end;
  gap: 8px;
  color: var(--text-tertiary);
  font-size: 12px;
  white-space: nowrap;
}
.leaf-meta strong { color: var(--text-primary); }
@media (max-width: 1100px) {
  .leaf-row { grid-template-columns: minmax(130px, 180px) minmax(260px, 1fr); row-gap: 6px; }
  .leaf-meta { justify-content: flex-start; }
}
@media (max-width: 760px) {
  .tree-header { align-items: flex-start; flex-direction: column; }
  .leaf-row { grid-template-columns: 1fr; }
  .branch-meta { margin-left: 0; }
  .branch-row { flex-wrap: wrap; }
}
</style>
