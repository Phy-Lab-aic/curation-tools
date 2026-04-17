# ScalarChart theme sync + divergence highlighting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the curation page's ScalarChart follow dark/warm theme changes live, unify joint colors per section (obs=blue, action=accent), and highlight per-frame action/observation divergence with yellow/red dim backgrounds on paired joints.

**Architecture:** One new hook (`useThemeVersion`) subscribes to root-element `style` mutations and returns a bump counter. `ScalarChart.tsx` drops its per-index color palette, reads unified CSS-var colors, and the inner `MiniChart` now accepts optional `bands: RatioBand[]` that paint the canvas before grid/line. Pairing and band computation are one pure function (`computeBands`) memoized per loaded episode.

**Tech Stack:** React 19, TypeScript, Vite. No unit-test runner in frontend — verification is manual/visual per task. Spec: `docs/superpowers/specs/2026-04-17-scalar-chart-theme-divergence-design.md`.

**Spec reference:**
- Thresholds: `ratio > 0.15` severe (red), `0.05 < ratio ≤ 0.15` moderate (yellow).
- Colors: obs = `var(--c-blue)`, action = `var(--accent)`, severe fill = `var(--c-red-dim)`, moderate fill = `var(--c-yellow-dim)`.
- Draw order: `--bg-deep` → moderate bands → severe bands → grid → line → cursor.

---

## File Structure

- **Create:** `frontend/src/hooks/useThemeVersion.ts` — small hook; returns a number that increments when `document.documentElement.style` changes.
- **Modify:** `frontend/src/components/ScalarChart.tsx` — remove palette, add `RatioBand` type + `computeBands`, wire `useThemeVersion`, unified section colors, render bands in `MiniChart`, replace hardcoded hex fallbacks with theme-var reads.

No other files change. `App.tsx` already mutates root `style` via `applyTheme` — the mutation observer picks that up.

---

### Task 1: Theme-version hook

**Files:**
- Create: `frontend/src/hooks/useThemeVersion.ts`

- [ ] **Step 1: Create the hook file**

Create `frontend/src/hooks/useThemeVersion.ts`:

```ts
import { useEffect, useState } from 'react'

/**
 * Returns a counter that increments whenever <html>'s inline `style`
 * attribute changes. The app's theme system (App.tsx `applyTheme`) sets
 * CSS custom properties via `documentElement.style.setProperty`, so this
 * hook gives canvas-based components a dependency they can react to.
 */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setVersion(v => v + 1)
    })
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style'],
    })
    return () => observer.disconnect()
  }, [])

  return version
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors for the new file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useThemeVersion.ts
git commit -m "feat(frontend): add useThemeVersion hook for canvas theme sync"
```

---

### Task 2: Unified colors + theme sync in ScalarChart (no bands yet)

Remove the per-index palette, apply the two section colors, wire `useThemeVersion` to force redraw on theme toggle, and replace every hardcoded hex in the file with a theme-var read. Bands come in Task 3 — keep this task scope tight for a clean visual verification.

**Files:**
- Modify: `frontend/src/components/ScalarChart.tsx`

- [ ] **Step 1: Update `MiniChart` signature and draw effect**

In `frontend/src/components/ScalarChart.tsx`, replace the existing `MiniChart` block (lines ~30–134) with the version below. Changes vs current:
- Add `themeVersion: number` prop.
- Include `themeVersion` in the draw effect deps.
- Replace hex fallbacks: bg fill drops `'#0f0f0f'`, grid reads `--border` instead of `'#1e1e1e'`, cursor reads `--text` instead of `'#fff'`.
- Replace `chartItem` border fallback `'#1a1a1a'` with `var(--border)` in the style map at the bottom of the file.

Replace the existing `MiniChart` component definition with:

```tsx
const MiniChart = memo(function MiniChart({ label, series, color, currentFrame, collapsed, themeVersion }: {
  label: string
  series: number[]
  color: string
  currentFrame: number
  collapsed: boolean
  themeVersion: number
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (collapsed) return
    const canvas = canvasRef.current
    if (!canvas || series.length === 0) return

    const draw = () => {
      const ctx = canvas.getContext('2d')
      if (!ctx) return

      const dpr = window.devicePixelRatio || 1
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (w === 0 || h === 0) return

      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.scale(dpr, dpr)

      const min = Math.min(...series)
      const max = Math.max(...series)
      const range = max - min || 1

      const cs = getComputedStyle(document.documentElement)
      const bg = cs.getPropertyValue('--bg-deep').trim()
      const gridColor = cs.getPropertyValue('--border').trim()
      const cursorColor = cs.getPropertyValue('--text').trim()

      // Background
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, w, h)

      // Grid lines
      ctx.strokeStyle = gridColor
      ctx.lineWidth = 1
      for (let i = 0; i < 4; i++) {
        const y = (h / 4) * i
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(w, y)
        ctx.stroke()
      }

      // Data line
      ctx.strokeStyle = color
      ctx.lineWidth = 1.5
      ctx.beginPath()
      const denom = Math.max(series.length - 1, 1)
      for (let i = 0; i < series.length; i++) {
        const x = (i / denom) * w
        const y = h - ((series[i] - min) / range) * (h - 4) - 2
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
      ctx.stroke()

      // Current frame indicator
      if (currentFrame >= 0 && currentFrame < series.length) {
        const x = (currentFrame / denom) * w
        ctx.strokeStyle = cursorColor
        ctx.lineWidth = 1
        ctx.setLineDash([2, 2])
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, h)
        ctx.stroke()
        ctx.setLineDash([])

        const y = h - ((series[currentFrame] - min) / range) * (h - 4) - 2
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(x, y, 3, 0, Math.PI * 2)
        ctx.fill()
      }
    }

    draw()
    const ro = new ResizeObserver(draw)
    ro.observe(canvas)
    return () => ro.disconnect()
  }, [series, color, currentFrame, collapsed, themeVersion])

  const currentVal = currentFrame >= 0 && currentFrame < series.length
    ? series[currentFrame].toFixed(3)
    : '--'

  return (
    <div style={chartStyles.chartItem}>
      <div style={chartStyles.chartHeader}>
        <span style={{ ...chartStyles.chartLabel, color }}>{label}</span>
        <span style={chartStyles.chartValue}>{currentVal}</span>
      </div>
      {!collapsed && (
        <canvas
          ref={canvasRef}
          style={chartStyles.canvas}
        />
      )}
    </div>
  )
})
```

- [ ] **Step 2: Remove palette and apply unified section colors in `ScalarChart`**

Delete the `getChartColors` helper (lines ~19–28). In the `ScalarChart` function body, remove the `COLORS` memo and import/use `useThemeVersion`. The obs mini-charts get `var(--c-blue)`, action mini-charts get `var(--accent)`.

Update the top of the file (imports) and the body as follows:

Change the imports at the top:

```tsx
import { useEffect, useMemo, useState, useRef, memo } from 'react'
import client from '../api/client'
import { useThemeVersion } from '../hooks/useThemeVersion'
```

Inside `export function ScalarChart(...)`, replace the line

```tsx
const COLORS = useMemo(getChartColors, [])
```

with:

```tsx
const themeVersion = useThemeVersion()
```

Replace the two `MiniChart` JSX blocks (obs and action `.map(...)`) with the unified-color versions:

```tsx
{obsKeys.map(key => (
  <MiniChart
    key={key}
    label={key.replace('observation.', '').replace('state.', '')}
    series={data.observations[key]}
    color="var(--c-blue)"
    currentFrame={currentFrame}
    collapsed={obsCollapsed}
    themeVersion={themeVersion}
  />
))}
```

```tsx
{actKeys.map(key => (
  <MiniChart
    key={key}
    label={key.replace('action.', '')}
    series={data.actions[key]}
    color="var(--accent)"
    currentFrame={currentFrame}
    collapsed={actCollapsed}
    themeVersion={themeVersion}
  />
))}
```

- [ ] **Step 3: Fix `chartItem` border fallback**

At the bottom of the file in `chartStyles`, change:

```tsx
chartItem: { padding: '3px 10px', borderBottom: '1px solid #1a1a1a', minWidth: 0 },
```

to:

```tsx
chartItem: { padding: '3px 10px', borderBottom: '1px solid var(--border)', minWidth: 0 },
```

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Visual verify — theme sync**

Run: `cd frontend && npm run dev` (background ok) and open the app. Navigate into any dataset → Curate tab → select an episode so ScalarChart is visible.

Do the following checks:
1. In the top-nav theme switcher, toggle **dark ↔ warm** repeatedly. The chart backgrounds, grid lines, and the dashed current-frame cursor should all change color immediately, with no page reload. Before this fix, the canvases stayed dark on the warm theme.
2. Observation.state section: all mini-chart lines are one blue color. Action section: all lines are one orange (accent) color. Labels in each section use the same color as the line.
3. The bottom border between mini-chart items stays a visible separator in both themes (should track `--border`).

If any item fails, fix before committing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ScalarChart.tsx
git commit -m "feat(frontend): unify ScalarChart colors per section and sync with theme"
```

---

### Task 3: Divergence bands

Add a pure `computeBands` helper that pairs obs/action by suffix, computes per-frame ratio, and produces merged runs of moderate/severe classification. Render those runs as rects in `MiniChart` between the bg fill and the grid.

**Files:**
- Modify: `frontend/src/components/ScalarChart.tsx`

- [ ] **Step 1: Add `RatioBand` type and `computeBands` helper**

Just above the `MiniChart` definition, add:

```tsx
type BandLevel = 'moderate' | 'severe'

interface RatioBand {
  start: number  // inclusive frame index
  end: number    // inclusive frame index
  level: BandLevel
}

const MODERATE_RATIO = 0.05
const SEVERE_RATIO = 0.15

function classify(ratio: number): BandLevel | null {
  if (ratio > SEVERE_RATIO) return 'severe'
  if (ratio > MODERATE_RATIO) return 'moderate'
  return null
}

function rangeOf(series: number[]): number {
  if (series.length === 0) return 0
  let min = series[0]
  let max = series[0]
  for (let i = 1; i < series.length; i++) {
    const v = series[i]
    if (v < min) min = v
    if (v > max) max = v
  }
  return max - min
}

/**
 * Pairwise obs/action divergence bands for a single joint.
 * Returns merged runs of consecutive frames at the same band level.
 * Returns [] if either input is empty or combined range is 0.
 */
function computeBands(obs: number[], act: number[]): RatioBand[] {
  const len = Math.min(obs.length, act.length)
  if (len === 0) return []
  const range = Math.max(rangeOf(obs), rangeOf(act))
  if (range === 0) return []

  const bands: RatioBand[] = []
  let curLevel: BandLevel | null = null
  let curStart = 0

  for (let i = 0; i < len; i++) {
    const ratio = Math.abs(act[i] - obs[i]) / range
    const level = classify(ratio)
    if (level !== curLevel) {
      if (curLevel !== null) {
        bands.push({ start: curStart, end: i - 1, level: curLevel })
      }
      curLevel = level
      curStart = i
    }
  }
  if (curLevel !== null) {
    bands.push({ start: curStart, end: len - 1, level: curLevel })
  }
  return bands
}

/**
 * Given an obs key like `observation.state.joint1`, returns `joint1`.
 * Given an act key like `action.joint1`, returns `joint1`.
 */
function unifyKey(key: string): string {
  return key.replace('observation.', '').replace('state.', '').replace('action.', '')
}
```

- [ ] **Step 2: Build `bandsByName` memo and pass to mini-charts**

Inside `ScalarChart`, just after `if (!data) return null` (before `obsKeys`/`actKeys` are derived), add:

```tsx
const obsKeys = Object.keys(data.observations)
const actKeys = Object.keys(data.actions)

const bandsByName = useMemo(() => {
  const map = new Map<string, RatioBand[]>()
  const actByName = new Map<string, number[]>()
  for (const k of actKeys) actByName.set(unifyKey(k), data.actions[k])
  for (const k of obsKeys) {
    const name = unifyKey(k)
    const act = actByName.get(name)
    if (!act) continue
    const bands = computeBands(data.observations[k], act)
    if (bands.length > 0) map.set(name, bands)
  }
  return map
}, [data])
```

Replace the two `.map(...)` blocks for obs/action with versions that look up bands:

```tsx
{obsKeys.map(key => {
  const name = key.replace('observation.', '').replace('state.', '')
  return (
    <MiniChart
      key={key}
      label={name}
      series={data.observations[key]}
      color="var(--c-blue)"
      currentFrame={currentFrame}
      collapsed={obsCollapsed}
      themeVersion={themeVersion}
      bands={bandsByName.get(name)}
    />
  )
})}
```

```tsx
{actKeys.map(key => {
  const name = key.replace('action.', '')
  return (
    <MiniChart
      key={key}
      label={name}
      series={data.actions[key]}
      color="var(--accent)"
      currentFrame={currentFrame}
      collapsed={actCollapsed}
      themeVersion={themeVersion}
      bands={bandsByName.get(name)}
    />
  )
})}
```

Note: `obsKeys`/`actKeys` must be declared before `useMemo(bandsByName, ...)` as shown. The `if (obsKeys.length === 0 && actKeys.length === 0) return null` guard stays exactly where it is (after the memo).

React hook rule: the `useMemo` must run unconditionally. Keep it before the early return. Reorder the block as:

```tsx
const obsKeys = Object.keys(data.observations)
const actKeys = Object.keys(data.actions)

const bandsByName = useMemo(() => {
  // ...as above
}, [data])

if (obsKeys.length === 0 && actKeys.length === 0) return null
```

- [ ] **Step 3: Render bands in `MiniChart`**

Update `MiniChart`'s prop type and draw effect. Add `bands?: RatioBand[]`, include it in deps, and draw rects after the bg fill and before grid.

Update the `MiniChart` prop destructure signature to:

```tsx
const MiniChart = memo(function MiniChart({ label, series, color, currentFrame, collapsed, themeVersion, bands }: {
  label: string
  series: number[]
  color: string
  currentFrame: number
  collapsed: boolean
  themeVersion: number
  bands?: RatioBand[]
}) {
```

Inside `draw()`, right after the `ctx.fillRect(0, 0, w, h)` background fill and before the grid-lines loop, add:

```tsx
      // Divergence bands (paint moderate first so severe overlaps win)
      if (bands && bands.length > 0 && series.length > 1) {
        const denomBand = Math.max(series.length - 1, 1)
        const moderateFill = cs.getPropertyValue('--c-yellow-dim').trim()
        const severeFill = cs.getPropertyValue('--c-red-dim').trim()
        for (const level of ['moderate', 'severe'] as const) {
          const fill = level === 'moderate' ? moderateFill : severeFill
          if (!fill) continue
          ctx.fillStyle = fill
          for (const b of bands) {
            if (b.level !== level) continue
            const x0 = (b.start / denomBand) * w
            const x1 = ((b.end + 1) / denomBand) * w
            ctx.fillRect(x0, 0, Math.max(x1 - x0, 1), h)
          }
        }
      }
```

Extend the effect's deps array to `[series, color, currentFrame, collapsed, themeVersion, bands]`.

- [ ] **Step 4: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Visual verify — bands**

With `npm run dev` still running, reload the curation view. Pick an episode that has both obs+act data with the same joint names (typical lerobot dataset under `/mnt/synology/data/data_div/2026_1/lerobot/`).

Do the following checks:
1. Paired joints (e.g. `joint1` exists under both obs and act): yellow dim regions appear where the two diverge moderately; red dim regions appear where they diverge severely. The yellow/red regions appear in **both** the obs and the action mini-chart of that joint at the same x range.
2. Joints that only appear in one section (unpaired) show the unified line color with no highlighting.
3. A near-perfect tracker shows no or few yellow regions. A noisy tracker shows more yellow, with occasional red.
4. Toggle dark ↔ warm: the band colors swap between the theme's `--c-yellow-dim` / `--c-red-dim` tokens and remain subtle (dim enough that the line stays readable).
5. Scrub the episode: the dashed cursor still renders cleanly over the bands.

If regions are too loud or too subtle, re-check that the fill is `--c-yellow-dim` / `--c-red-dim` (not `--c-yellow` / `--c-red`). If ratios look wrong (e.g. always fully highlighted), recheck that `range` uses `max(rangeOf(obs), rangeOf(act))` rather than the sum.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ScalarChart.tsx
git commit -m "feat(frontend): highlight action/observation divergence in ScalarChart"
```

---

## Self-Review

- **Spec coverage.** Theme sync → Task 2. Hardcoded-hex replacements → Task 2. Unified section colors → Task 2. Pairing rule + `computeBands` + thresholds + draw order → Task 3. Edge cases (unpaired, length mismatch, zero range, N=1) → covered by `computeBands` guards and the `denom = Math.max(series.length - 1, 1)` fix in both draw functions. Unit tests — skipped per spec's conditional; no vitest configured.
- **Placeholder scan.** None. Every step has full code or an exact command.
- **Type consistency.** `RatioBand`, `BandLevel`, `unifyKey`, `computeBands` signatures and call sites match across Task 3 steps. `themeVersion` prop threaded consistently in Task 2 step 1 (MiniChart) and Task 2 step 2 (call sites).

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-17-scalar-chart-theme-divergence.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
