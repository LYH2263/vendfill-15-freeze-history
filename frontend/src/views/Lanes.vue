<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const current = ref<any>(null)
const savedSlot = ref<string | null>(null)

async function loadLanes() { rows.value = await api('/lanes?location_id=1') }
async function loadCurrent() { current.value = await api('/refills/current?location_id=1') }

async function save(r: any) {
  // 只写货道（现算世代输入）。历史补货单行项目冻结，不被此操作改写。
  const updated = await api(`/lanes/${r.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ stock: Number(r.stock), in_transit: Number(r.in_transit), capacity: Number(r.capacity) }),
  })
  savedSlot.value = r.slot_no
  Object.assign(r, updated)
  await loadCurrent()
}

onMounted(async () => { await Promise.all([loadLanes(), loadCurrent()]) })
</script>
<template>
  <h1>货道格子</h1>
  <p class="sub">改库存 / 在途 / 容量并保存，仅影响「当前缺口」与之后生成的新单；历史单冻结不变</p>
  <div class="vf-machine-layout">
    <div class="vf-slot-grid">
      <div v-for="r in rows" :key="r.id" class="vf-slot">
        <div class="vf-slot-no">{{ r.slot_no }}</div>
        <div class="vf-slot-sku">{{ r.sku_name }}</div>
        <div class="vf-slot-bar">
          <div
            class="vf-slot-fill"
            :class="{ 'vf-need': r.gap > 0 }"
            :style="{ width: Math.min(r.fill_pct, 100) + '%' }"
          />
        </div>
        <div class="vf-slot-meta">{{ r.stock }}/{{ r.capacity }} · 缺 {{ r.gap }}</div>
        <div class="vf-edit">
          <label>库<input type="number" v-model.number="r.stock" /></label>
          <label>途<input type="number" v-model.number="r.in_transit" /></label>
          <label>容<input type="number" v-model.number="r.capacity" /></label>
          <button class="btn vf-mini" @click="save(r)">保存</button>
        </div>
        <span v-if="savedSlot === r.slot_no" class="vf-saved-tip">已保存·历史单不变</span>
      </div>
    </div>
    <aside class="vf-receipt" v-if="current">
      <h2>*** 当前缺口 · 现算 ***</h2>
      <div class="vf-receipt-line" v-for="l in current.lines" :key="l.lane_id">
        <span>{{ l.slot_no }} {{ l.sku_name }}</span>
        <span>x{{ l.fill_qty }}</span>
      </div>
      <p class="muted" style="margin:0.75rem 0 0;font-size:0.72rem;color:#6a5e48;text-align:center">
        — 现算预览，不落库 · 去「补货小票」生成才会冻结新一代 —
      </p>
    </aside>
  </div>
</template>
<style scoped>
.vf-edit { display: flex; gap: 0.25rem; align-items: center; margin-top: 0.35rem; flex-wrap: wrap; }
.vf-edit label { font-size: 0.58rem; color: var(--vf-dim); display: flex; align-items: center; gap: 0.15rem; }
.vf-edit input {
  width: 40px; background: #0a0e14; color: var(--vf-text);
  border: 1px solid #3a4454; border-radius: 3px; padding: 0.1rem 0.2rem; font-size: 0.66rem;
}
.vf-mini { padding: 0.15rem 0.4rem; font-size: 0.66rem; margin-left: auto; }
.vf-saved-tip { font-size: 0.56rem; color: var(--vf-led); margin-top: 0.2rem; }
</style>
