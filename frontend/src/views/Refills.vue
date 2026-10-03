<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const orders = ref<any[]>([])
const detail = ref<any>(null)
const current = ref<any>(null)
const tab = ref<'order' | 'current'>('order')
const busy = ref(false)

const fmt = (iso: string) => (iso || '').replace('T', ' ').slice(0, 19)
const statusText = (s: string) => s === 'need_fill' ? '待补' : s === 'full' ? '满仓' : '超占'

async function loadOrders() { orders.value = await api('/refills/orders?location_id=1') }
async function open(id: number) {
  detail.value = await api(`/refills/orders/${id}`)
  tab.value = 'order'
}
async function showCurrent() {
  current.value = await api('/refills/current?location_id=1')
  tab.value = 'current'
}
async function run() {
  busy.value = true
  try {
    const o = await api('/refills/run?location_id=1', { method: 'POST' })
    await loadOrders()
    await open(o.id)
  } finally { busy.value = false }
}
onMounted(async () => {
  await loadOrders()
  current.value = await api('/refills/current?location_id=1')
  if (orders.value.length) await open(orders.value[0].id)
})
const latestId = computed(() => orders.value[0]?.id)
</script>

<template>
  <h1>补货单</h1>
  <p class="sub">生成即冻结 · 历史单不跟货道变动 · 「当前缺口」才是现算</p>
  <div style="display:flex;gap:0.5rem;margin-bottom:1rem">
    <button class="btn" :disabled="busy" @click="run">生成补货单</button>
    <button class="btn btn-ghost" @click="showCurrent">当前缺口（现算）</button>
  </div>
  <div class="vf-machine-layout">
    <div class="card">
      <div class="muted" style="font-size:0.75rem;margin-bottom:0.5rem">历史单（新→旧，点选查看冻结详情）</div>
      <table>
        <thead><tr><th>单号</th><th>生成时间</th><th>总补量</th><th>待补道数</th><th>标记</th></tr></thead>
        <tbody>
          <tr v-for="o in orders" :key="o.id" style="cursor:pointer"
              :class="{ 'vf-row-active': tab === 'order' && detail?.id === o.id }"
              @click="open(o.id)">
            <td>#{{ o.id }}</td>
            <td>{{ fmt(o.created_at) }}</td>
            <td>{{ o.total_fill }}</td>
            <td>{{ o.need_fill_count }}</td>
            <td>
              <span v-if="o.id === latestId" class="badge badge-ok">最新有效单</span>
              <span v-if="o.has_drift" class="badge badge-bad">行已漂移</span>
            </td>
          </tr>
          <tr v-if="!orders.length"><td colspan="5" class="muted">暂无历史单，点「生成补货单」冻结第一单</td></tr>
        </tbody>
      </table>
    </div>

    <aside v-if="tab === 'current' && current" class="vf-receipt">
      <h2>*** 当前缺口 · 现算 ***</h2>
      <p style="text-align:center;margin:0 0 0.5rem;font-size:0.7rem;color:#8a5a2a">
        未冻结 · 跟当前货道实时计算 · 不落库
      </p>
      <div class="vf-receipt-line" v-for="l in current.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }} <small>({{ statusText(l.status) }})</small></span>
        <span>{{ l.fill_qty }} / 缺{{ l.gap }}</span>
      </div>
      <p style="text-align:center;margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48">
        合计 {{ current.total_fill }} · 点「生成补货单」才冻结成单
      </p>
    </aside>

    <aside v-else-if="detail" class="vf-receipt">
      <h2>*** VendFill 补货单 #{{ detail.id }} ***</h2>
      <p style="text-align:center;margin:0 0 0.5rem;font-size:0.7rem;color:#6a5e48">
        冻结于 {{ fmt(detail.created_at) }} · 不随后续货道变动
      </p>
      <p v-if="detail.has_drift" class="vf-drift-banner">
        ⚠ 本单存在漂移：以下显示为库内原文，系统未做修复
      </p>
      <template v-if="!detail.corrupt">
        <div class="vf-receipt-line" style="font-weight:700;border-bottom:2px dashed #8a7e64">
          <span>货道 / 商品</span><span>补量</span>
        </div>
        <div class="vf-receipt-line" v-for="l in detail.lines" :key="l.lane_id"
             :class="{ 'vf-line-drifted': l.drifted }">
          <span>{{ l.slot_no }} {{ l.sku_name }}
            <small>({{ statusText(l.status) }})</small>
            <span v-if="l.drifted" class="badge badge-bad">行已漂移</span>
          </span>
          <span>{{ l.fill_qty }} / 缺{{ l.gap }}</span>
        </div>
        <p style="text-align:center;margin:1rem 0 0;font-size:0.72rem;color:#6a5e48">
          合计 {{ detail.total_fill }} · 待补 {{ detail.need_fill_count }} 道 · 谢谢使用
        </p>
      </template>
      <template v-else>
        <p style="font-size:0.72rem;color:#8a5a2a">库内文本已损坏，原样展示：</p>
        <pre class="vf-raw">{{ detail.raw }}</pre>
      </template>
    </aside>
  </div>
</template>
