<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const current = ref<any>(null)
const editing = ref<Record<number, any>>({})
const saving = ref(0)

async function load() {
  rows.value = await api('/lanes?location_id=1')
  // 现算世代：只读当前缺口，不生成单、不碰历史单
  current.value = await api('/refills/current?location_id=1')
}
function startEdit(r: any) {
  editing.value[r.id] = { stock: r.stock, in_transit: r.in_transit, capacity: r.capacity }
}
function cancelEdit(id: number) { delete editing.value[id] }
async function save(r: any) {
  const p = editing.value[r.id]
  saving.value = r.id
  try {
    await api(`/lanes/${r.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ stock: +p.stock, in_transit: +p.in_transit, capacity: +p.capacity }),
    })
    cancelEdit(r.id)
    await load()  // 历史补货单已冻结，此处只刷新货道与现算缺口
  } finally { saving.value = 0 }
}
onMounted(load)
</script>

<template>
  <h1>货道格子</h1>
  <p class="sub">改数保存只影响新缺口 · 已冻结的历史补货单不会被改写</p>
  <div class="vf-machine-layout">
    <div class="vf-slot-grid">
      <div v-for="r in rows" :key="r.id" class="vf-slot">
        <div class="vf-slot-no">{{ r.slot_no }}</div>
        <div class="vf-slot-sku">{{ r.sku_name }}</div>
        <template v-if="!editing[r.id]">
          <div class="vf-slot-bar">
            <div
              class="vf-slot-fill"
              :class="{ 'vf-need': r.gap > 0 }"
              :style="{ width: Math.min(r.fill_pct, 100) + '%' }"
            />
          </div>
          <div class="vf-slot-meta">{{ r.stock }}/{{ r.capacity }} · 在途 {{ r.in_transit }} · 缺 {{ r.gap }}</div>
          <button class="vf-mini-btn" @click="startEdit(r)">改数</button>
        </template>
        <template v-else>
          <label class="vf-slot-field">库存
            <input type="number" min="0" v-model="editing[r.id].stock" />
          </label>
          <label class="vf-slot-field">在途
            <input type="number" min="0" v-model="editing[r.id].in_transit" />
          </label>
          <label class="vf-slot-field">容量
            <input type="number" min="0" v-model="editing[r.id].capacity" />
          </label>
          <div style="display:flex;gap:0.25rem;margin-top:0.25rem">
            <button class="vf-mini-btn" :disabled="saving === r.id" @click="save(r)">保存</button>
            <button class="vf-mini-btn vf-mini-ghost" @click="cancelEdit(r.id)">取消</button>
          </div>
        </template>
      </div>
    </div>
    <aside class="vf-receipt" v-if="current">
      <h2>*** 当前缺口 · 现算 ***</h2>
      <div class="vf-receipt-line" v-for="l in current.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}</span>
        <span>x{{ l.fill_qty }}</span>
      </div>
      <p class="muted" style="margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48;text-align:center">
        — 未冻结 · 去「补货单」页生成才落库 —
      </p>
    </aside>
  </div>
</template>
