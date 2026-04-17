# ScalarChart theme sync + action/observation divergence highlighting

**Date:** 2026-04-17
**Scope:** `frontend/src/components/ScalarChart.tsx` (primary), minor CSS var usage audit in related curation-right panel if needed.

## Problem

The curation page's right-side ScalarChart panel has two issues:

1. **Theme mismatch.** The app supports a `dark` and `warm` theme (set in `App.tsx` via `applyTheme`), but `ScalarChart` canvas rendering only redraws when `series`, `color`, `currentFrame`, or `collapsed` change. Toggling the theme leaves the already-painted canvas with the old background color and old hardcoded grid/cursor colors (`'#1e1e1e'`, `'#fff'`, `'#0f0f0f'`). The canvas also uses `'#1a1a1a'` as a hardcoded `chartItem` border.

2. **Per-index chart colors + no divergence signal.** Each observation.state and action joint is rendered in a different color from a rotating `--chart-1…6` palette. This reads as decorative. What a curator cares about is: *does the observed state track the commanded action?* Large tracking error is a likely sign of a bad episode.

## Goals

- ScalarChart canvases (background, grid, cursor, data line) remain visually correct across theme changes with no reload.
- Observation.state joints render in a single color; action joints render in a single different color. Differences between paired joints are surfaced visually so a curator can see where tracking diverged.

## Non-goals

- No threshold configuration UI. Defaults are fixed in this iteration.
- No change to the terminal-frames bar, grade bar, or left episode list.
- No change to data fetch shape (`/scalars/:idx` API). Pairing is derived client-side from existing keys.

## Design

### 1. Theme sync

**Trigger redraws on theme change.** `applyTheme` in `App.tsx` mutates `document.documentElement.style` inline. The mini-chart draw effect already reads `getComputedStyle(document.documentElement)` at draw time, so the missing piece is *triggering a redraw* when theme changes.

Approach: Introduce a small `useTheme` hook that subscribes to the root element's `style` attribute via `MutationObserver` and returns a `themeVersion` number that bumps on change. `MiniChart` reads this value and includes it in its draw `useEffect` dependency list. No other component needs the hook yet.

```
// frontend/src/hooks/useThemeVersion.ts
export function useThemeVersion(): number
```

Implementation:
- Create `MutationObserver` once on mount, watching `document.documentElement` for `attributes: true, attributeFilter: ['style']`.
- On each mutation, `setVersion(v => v + 1)`.
- Cleanup on unmount.

**Replace hardcoded colors in `ScalarChart.tsx`:**
- Background fill `'#0f0f0f'` fallback → keep `var(--bg-deep)` read, drop the hex fallback (theme always sets it).
- Grid stroke `'#1e1e1e'` fallback → read `--border` instead.
- Current-frame dashed line `'#fff'` → read `--text`.
- `chartItem` CSS `borderBottom: '1px solid #1a1a1a'` → `var(--border)`.

The per-joint line color (the `color` prop) is taken from the unified color decision in §2, not a hardcoded palette value.

### 2. Unified joint colors + divergence highlighting

**Unified colors.**

- Observation.state columns: every mini-chart line uses `var(--c-blue)`.
- Action columns: every mini-chart line uses `var(--accent)`.

The existing `COLORS` palette and `i % COLORS.length` indexing are removed from `ScalarChart`. The palette tokens themselves (`--chart-1…6`) stay in the theme (other components may use them).

**Pairing rule.** Before rendering, compute pairs by suffix match:

- Observation key `observation.state.{name}` ↔ Action key `action.{name}`.
- Derive `name` using the same prefix-strip already applied in labels (`.replace('observation.', '').replace('state.', '')` for obs; `.replace('action.', '')` for action).
- A joint with no counterpart remains unpaired — rendered in the unified color, no highlight.

**Divergence measurement.** For each paired joint:

```
len = min(obs.length, act.length)
range = max(max(obs) - min(obs), max(act) - min(act))
if range == 0: no highlight
for i in 0..len:
    ratio[i] = |act[i] - obs[i]| / range
```

Thresholds:
- `ratio > 0.15` → severe (red)
- `0.05 < ratio ≤ 0.15` → moderate (yellow)
- else → no highlight

**Highlight rendering.** After filling the chart background and before drawing grid lines and the data line, paint per-frame vertical rect strips:

- Severe frames: `fillStyle = var(--c-red-dim)` (rgba already has alpha in theme).
- Moderate frames: `fillStyle = var(--c-yellow-dim)`.
- Strip x-extent for frame `i`: `[i/(N-1) * w, (i+1)/(N-1) * w]`, merged into runs so adjacent same-class frames become one rect (avoids seams).
- Height: full canvas height.

Draw order per mini-chart canvas:
1. `--bg-deep` fill (full canvas).
2. Divergence strips (yellow under red; i.e. paint moderate first, then severe, so overlaps favor severe).
3. Grid lines.
4. Data line in unified color.
5. Current-frame dashed cursor + value dot.

The same `ratio` array is applied to **both** the obs and the act mini-chart of that paired joint — highlights appear in the same x-range in both charts, making the pair legible at a glance.

**Data plumbing.** `ScalarChart` computes a `Map<string, RatioBand[]>` keyed by unified joint `name`, where `RatioBand = { start: number; end: number; level: 'moderate' | 'severe' }` (runs of consecutive frames at the same level). This is computed once per `data` load (`useMemo`), then passed to `MiniChart` as an optional `bands?: RatioBand[]` prop. Unpaired charts pass `undefined`.

### Component changes

`ScalarChart.tsx`:
- Remove `getChartColors` and `COLORS`.
- Add `useThemeVersion` import; pass through to `MiniChart`.
- Add `computeBands(obs, act)` helper.
- Add `useMemo` building `bandsByName` from `data`.
- For each rendered `MiniChart`: pick color by section (`var(--c-blue)` obs / `var(--accent)` action); pick bands from `bandsByName.get(name)`.

`MiniChart` (inside `ScalarChart.tsx`):
- Add `bands?: RatioBand[]`, `themeVersion: number` props.
- Include `bands`, `themeVersion` in draw effect deps.
- Replace hardcoded hex fallbacks with theme-var reads.
- Paint bands between bg fill and grid.

New: `frontend/src/hooks/useThemeVersion.ts` — single-responsibility hook.

### Edge cases

| Case | Behavior |
|---|---|
| Theme toggled mid-session | `themeVersion` bumps → all visible canvases redraw. |
| Unpaired joint | Unified color only, no bands. |
| `obs.length !== act.length` | Compare only first `min(len)` frames; bands stop there. |
| Constant series (`range == 0`) | No bands for that pair. |
| `N == 1` single-frame episode | Strip math guards against divide-by-zero by treating width as `w` when `N == 1`. |
| Collapsed section | No redraw work (existing guard stays). |
| `--c-yellow-dim` / `--c-red-dim` read fails | Fall back to no highlight rather than raw hex (keep rendering correct across any future theme that forgets these tokens). |

### Testing

- **Manual/visual:** load a dataset with obs+act pairs; toggle dark↔warm → backgrounds, grid, cursor, and band dim colors all update without reload.
- **Manual:** scrub through an episode where action leads observation — expect yellow/red bands co-located in both columns on matching joints.
- **Unit (vitest, if present):** `computeBands` pure function — given obs/act arrays, returns expected `RatioBand[]` for constant, identical, and divergent inputs. (Confirm test stack in plan step; skip if no frontend test runner is wired.)

## Rollout

Single PR. No feature flag, no migration. Visible change for all curators once merged.

## Open questions resolved

- Threshold: 5% / 15% of per-pair range — confirmed.
- Visualization: background highlighting only, no line color splitting — confirmed.
- Unified colors: blue for obs, accent (orange in dark / dark-orange in warm) for action — chosen to match existing semantic tokens and provide strong contrast in both themes.
