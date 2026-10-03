<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

type Tab = 'current' | 'history'
const tab = ref<Tab>('current')
const loading = ref(false)
const saved = ref(false)

// —— 货道现算世代（不落库，随库存/在途/容量实时变化）——
const current = ref<any>(null)

// —— 冻结历史世代（一旦生成，行项目不再随货道变化）——
const orders = ref<any[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<any>(null)

async function loadCurrent() {
  current.value = await api('/refills/current?location_id=1')
}
async function loadList() {
  orders.value = await api('/refills?location_id=1')
}
async function selectOrder(id: number) {
  selectedId.value = id
  detail.value = await api(`/refills/${id}`)
}

async function generate() {
  // 唯一会生成历史单的入口：此刻按当前货道算一次并冻结为新一代
  loading.value = true
  saved.value = false
  try {
    const o = await api('/refills/run?location_id=1', { method: 'POST' })
    await loadList()
    await selectOrder(o.id)
    await loadCurrent()
    tab.value = 'history'
  } finally {
    loading.value = false
  }
}

async function saveLane(l: any) {
  // 货道现算世代的输入：保存只影响「当前缺口」与之后新生成的单，绝不回写历史
  await api(`/lanes/${l.lane_id}`, {
    method: 'PATCH',
    body: JSON.stringify({ stock: Number(l.stock), in_transit: Number(l.in_transit), capacity: Number(l.capacity) }),
  })
  saved.value = true
  await loadCurrent()
  if (tab.value === 'history' && selectedId.value) await selectOrder(selectedId.value)
}

function statusText(s: string) {
  return s === 'need_fill' ? '待补' : s === 'full' ? '满仓' : '超占'
}

onMounted(async () => {
  await Promise.all([loadCurrent(), loadList()])
})
</script>

<template>
  <h1>补货小票</h1>
  <p class="sub">历史单（冻结）与当前缺口（货道现算）严格分世代 · 混代即废</p>

  <div class="vf-tabs">
    <button class="vf-tab" :class="{ on: tab === 'current' }" @click="tab = 'current'">当前缺口 · 现算</button>
    <button class="vf-tab" :class="{ on: tab === 'history' }" @click="tab = 'history'">
      历史补货单 · 冻结
      <span class="vf-tab-count">{{ orders.length }}</span>
    </button>
  </div>

  <!-- ============ 货道现算世代 ============ -->
  <div v-if="tab === 'current'" class="vf-gen-grid">
    <div v-if="current">
      <div class="card" style="max-width:560px">
        <strong style="color:var(--vf-amber)">当前缺口（现算 · 不落库）</strong>
        <p class="muted" style="margin:0.35rem 0 0;font-size:0.74rem">
          数字跟随货道最新库存 / 在途 / 容量实时变化，不会修改任何历史单。可直接在下表改数保存。
        </p>
      </div>
      <div class="card" style="max-width:560px;overflow:auto">
        <table>
          <thead><tr><th>货道</th><th>商品</th><th>库存</th><th>在途</th><th>容量</th><th>缺口</th><th>现算补量</th><th></th></tr></thead>
          <tbody>
            <tr v-for="l in current.lines" :key="l.lane_id">
              <td>{{ l.slot_no }}</td><td>{{ l.sku_name }}</td>
              <td><input class="vf-num" v-model.number="l.stock" /></td>
              <td><input class="vf-num" v-model.number="l.in_transit" /></td>
              <td><input class="vf-num" v-model.number="l.capacity" /></td>
              <td>{{ l.gap }}</td><td>{{ l.fill_qty }}</td>
              <td><button class="btn vf-mini" @click="saveLane(l)">保存</button></td>
            </tr>
          </tbody>
        </table>
        <span v-if="saved" class="muted" style="font-size:0.72rem">已保存到货道；历史单不变，仅当前缺口与下一单受影响。</span>
      </div>
    </div>
    <div>
      <button class="btn" :disabled="loading" @click="generate">
        {{ loading ? '生成中…' : '生成补货单（冻结为新一代）' }}
      </button>
      <p class="muted" style="font-size:0.72rem;max-width:260px;margin:0.5rem 0 1rem">
        生成后该单行项目立即冻结；之后再改货道，打开它仍是生成当时的补量与状态。
      </p>
      <div class="vf-receipt" v-if="current">
        <h2>*** 当前缺口（现算）***</h2>
        <div class="vf-receipt-line" style="font-weight:700;border-bottom:2px dashed #8a7e64">
          <span>货道 / 商品</span><span>现算补量</span>
        </div>
        <div class="vf-receipt-line" v-for="l in current.lines" :key="l.lane_id">
          <span>{{ l.slot_no }} {{ l.sku_name }} <small>({{ statusText(l.status) }})</small></span>
          <span>{{ l.fill_qty }} / 缺{{ l.gap }}</span>
        </div>
        <p style="text-align:center;margin:1rem 0 0;font-size:0.72rem;color:#6a5e48">现算视图 · 未冻结</p>
      </div>
    </div>
  </div>

  <!-- ============ 冻结历史世代 ============ -->
  <div v-else class="vf-gen-grid">
    <div class="card" style="max-width:340px">
      <strong>历史单（新→旧）</strong>
      <p class="muted" style="font-size:0.72rem;margin:0.25rem 0 0.6rem">点任一条查看冻结详情；改货道不会改写这里。</p>
      <div v-if="!orders.length" class="muted" style="font-size:0.78rem">还没有生成过补货单。</div>
      <button
        v-for="o in orders" :key="o.id"
        class="vf-order-item" :class="{ on: o.id === selectedId }"
        @click="selectOrder(o.id)"
      >
        <span class="vf-order-gen">第 {{ o.generation }} 代</span>
        <span class="muted" style="font-size:0.7rem">#{{ o.id }} · {{ o.created_at?.slice(0, 16).replace('T', ' ') }}</span>
        <span class="vf-order-total">补量合计 {{ o.total_fill ?? '—' }}</span>
        <span v-if="o.drift" class="badge badge-bad">
          行已漂移{{ o.lines_corrupt ? '·文本损坏' : `·${o.drift_line_count}行` }}
        </span>
      </button>
    </div>

    <div v-if="detail">
      <div class="card" v-if="detail.drift" style="border-color:var(--vf-red);max-width:460px">
        <span class="badge badge-bad">行已漂移</span>
        <span style="font-size:0.76rem;margin-left:0.4rem">库内行文本与生成时冻结签名不一致，已原样读出，系统未写回修复。</span>
        <ul style="margin:0.4rem 0 0;font-size:0.74rem;color:var(--vf-red)">
          <li v-for="(reason, key) in detail.lines_drift" :key="key">货道 lane {{ key }}：{{ reason }}</li>
          <li v-for="m in detail.missing_lines" :key="m">货道 lane {{ m }}：行缺失（被删除）</li>
          <li v-if="detail.lines_corrupt">行 JSON 已被截断/损坏，无法解析为行。</li>
        </ul>
      </div>

      <div class="vf-receipt">
        <h2>*** 第 {{ detail.generation }} 代补货单（冻结）***</h2>
        <div style="font-size:0.68rem;text-align:center;color:#6a5e48;margin-bottom:0.4rem">
          {{ detail.created_at }} · 生成当时快照
        </div>

        <template v-if="!detail.lines_corrupt">
          <div class="vf-receipt-line" style="font-weight:700;border-bottom:2px dashed #8a7e64">
            <span>货道 / 商品</span><span>补量 / 缺口</span>
          </div>
          <div class="vf-receipt-line" v-for="l in detail.lines" :key="l.lane_id">
            <span>{{ l.slot_no }} {{ l.sku_name }}
              <small>({{ statusText(l.status) }})</small>
              <span v-if="l.line_drift" class="badge badge-bad" style="margin-left:4px">行已漂移</span>
            </span>
            <span :style="l.line_drift ? 'color:#c0392b;font-weight:700' : ''">{{ l.fill_qty }} / 缺{{ l.gap }}</span>
          </div>
        </template>

        <div v-else>
          <p style="font-weight:700;color:#c0392b">行文本已损坏，以下为库内原始脏文本（原样显示，未修复）：</p>
          <pre class="vf-dirty-raw">{{ detail.raw_lines_text }}</pre>
        </div>

        <p style="text-align:center;margin:1rem 0 0;font-size:0.72rem;color:#6a5e48">
          冻结世代 · 不随后续货道改动变化
        </p>
      </div>
    </div>
    <div v-else class="muted">← 从左侧选择一条历史单</div>
  </div>
</template>

<style scoped>
.vf-tabs { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
.vf-tab {
  background: var(--vf-face); color: var(--vf-dim); border: 1px solid #3a4454;
  border-radius: 4px; padding: 0.45rem 0.9rem; cursor: pointer; font-size: 0.8rem;
}
.vf-tab.on { color: #041208; background: var(--vf-led); border-color: var(--vf-led); font-weight: 800; }
.vf-tab-count { font-size: 0.68rem; background: rgba(0,0,0,0.25); border-radius: 8px; padding: 0 0.4rem; margin-left: 0.3rem; }
.vf-gen-grid {
  display: grid; grid-template-columns: 1fr minmax(280px, 460px); gap: 1rem; align-items: start;
}
@media (max-width: 1000px) { .vf-gen-grid { grid-template-columns: 1fr; } }
.vf-num { width: 56px; background: #0a0e14; color: var(--vf-text); border: 1px solid #3a4454; border-radius: 3px; padding: 0.2rem 0.3rem; }
.vf-mini { padding: 0.2rem 0.5rem; font-size: 0.72rem; }
.vf-order-item {
  display: block; width: 100%; text-align: left; margin-top: 0.4rem;
  background: var(--vf-glass); border: 1px solid #3a4454; border-radius: 4px;
  padding: 0.5rem 0.6rem; cursor: pointer; color: var(--vf-text);
}
.vf-order-item.on { border-color: var(--vf-led); box-shadow: inset 0 0 0 1px var(--vf-led); }
.vf-order-gen { font-weight: 800; color: var(--vf-led); margin-right: 0.5rem; }
.vf-order-total { display: block; font-size: 0.76rem; margin-top: 0.15rem; }
.vf-dirty-raw {
  white-space: pre-wrap; word-break: break-all; background: #f3e4c0;
  border: 1px dashed #b0892f; padding: 0.5rem; font-size: 0.66rem; color: #7a3b2e;
}
</style>
