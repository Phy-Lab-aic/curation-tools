# Overview Chart Interaction + Visual Improvements

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make overview charts clickable to navigate to curate with filters, and improve chart visual design (ghost gradient, larger text, time units).

**Architecture:** Extend `AppState` with optional `CurateFilter` to carry filter context when navigating from overview to curate. DatasetPage filters episodes by length/tag before passing to EpisodeList. EpisodeList shows filter chips and initializes grade filter from props. Chart visuals use SVG linearGradient for ghost gradient effect.

**Tech Stack:** React, TypeScript, recharts, CSS custom properties

**Spec:** `docs/superpowers/specs/2026-04-15-overview-interaction-design.md`

---

### File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/src/types/index.ts` | Modify | Add `CurateFilter` type, extend `AppState` |
| `frontend/src/hooks/useAppState.ts` | Modify | Extend `setTab` to accept filter |
| `frontend/src/App.tsx` | Modify | Pass `setTab` + `filter` to DatasetPage |
| `frontend/src/components/DatasetPage.tsx` | Modify | Accept filter/setTab, filter episodes, pass callbacks |
| `frontend/src/components/OverviewTab.tsx` | Modify | Ghost gradient, axis text, time labels, click handlers |
| `frontend/src/components/EpisodeList.tsx` | Modify | Filter chip UI, initial grade filter from prop |
| `frontend/src/App.css` | Modify | Filter chip styles |

---

### Task 1: Types + State + Prop Threading

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/hooks/useAppState.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/DatasetPage.tsx`

- [ ] **Step 1: Add CurateFilter type and extend AppState**

In `frontend/src/types/index.ts`, add the filter type and update the dataset view state:

```typescript
// Add after the DatasetTab type (line 66)
export interface CurateFilter {
  grade?: string
  lengthRange?: [number, number]
  tag?: string
}
```

Update the dataset variant of `AppState` to include optional filter:

```typescript
// Change line 71 from:
| { view: 'dataset'; cellName: string; cellPath: string; datasetPath: string; datasetName: string; tab: DatasetTab }
// To:
| { view: 'dataset'; cellName: string; cellPath: string; datasetPath: string; datasetName: string; tab: DatasetTab; filter?: CurateFilter }
```

- [ ] **Step 2: Extend setTab in useAppState**

In `frontend/src/hooks/useAppState.ts`, update the `setTab` function and its type:

```typescript
// Change the return type interface (around line 11) from:
setTab: (tab: DatasetTab) => void
// To:
setTab: (tab: DatasetTab, filter?: CurateFilter) => void
```

Add `CurateFilter` to the import:

```typescript
import type { AppState, DatasetTab, CurateFilter } from '../types'
```

Update the `setTab` implementation:

```typescript
// Change from:
const setTab = useCallback((tab: DatasetTab) => {
    setState(prev =>
      prev.view === 'dataset' ? { ...prev, tab } : prev
    )
  }, [])
// To:
const setTab = useCallback((tab: DatasetTab, filter?: CurateFilter) => {
    setState(prev =>
      prev.view === 'dataset' ? { ...prev, tab, filter } : prev
    )
  }, [])
```

- [ ] **Step 3: Thread props through App → DatasetPage**

In `frontend/src/App.tsx`, pass `setTab` and filter to DatasetPage. Update the dataset view rendering:

```tsx
// Change from (around line 63):
{state.view === 'dataset' && (
  <DatasetPage
    datasetPath={state.datasetPath}
    datasetName={state.datasetName}
    tab={state.tab}
  />
)}
// To:
{state.view === 'dataset' && (
  <DatasetPage
    datasetPath={state.datasetPath}
    datasetName={state.datasetName}
    tab={state.tab}
    filter={state.filter}
    onSetTab={setTab}
  />
)}
```

- [ ] **Step 4: Accept new props in DatasetPage**

In `frontend/src/components/DatasetPage.tsx`, update the props interface and add import:

```typescript
import type { CurateFilter, DatasetTab, Episode } from '../types'

interface DatasetPageProps {
  datasetPath: string
  datasetName: string
  tab: DatasetTab
  filter?: CurateFilter
  onSetTab: (tab: DatasetTab, filter?: CurateFilter) => void
}
```

Update the component signature to destructure the new props:

```typescript
export function DatasetPage({ datasetPath, datasetName: _datasetName, tab, filter, onSetTab }: DatasetPageProps) {
```

- [ ] **Step 5: Verify dev server starts without errors**

Run: `cd frontend && npx vite --host 2>&1 | head -20`

Check: No TypeScript errors, dev server starts.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/hooks/useAppState.ts frontend/src/App.tsx frontend/src/components/DatasetPage.tsx
git commit -m "feat: add CurateFilter type and thread filter state through components"
```

---

### Task 2: Chart Visual — Ghost Gradient + Axis Text

**Files:**
- Modify: `frontend/src/components/OverviewTab.tsx`

- [ ] **Step 1: Update ChartPanel to use ghost gradient bars**

In `frontend/src/components/OverviewTab.tsx`, replace the `ChartPanel` function (lines 198-235) with:

```tsx
function ChartPanel({ chart, color }: { chart: DistributionResult; color: string }) {
  const gradientId = `gradient-${chart.field}`

  return (
    <div className="chart-panel">
      <div className="chart-panel-header">
        <span className="chart-panel-title">{FIELD_LABELS[chart.field] ?? chart.field}</span>
        <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>{chart.total}</span>
      </div>
      <div className="chart-panel-body">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart.bins} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="1" x2="0" y2="0">
                <stop offset="0%" stopColor={color} stopOpacity={0.25} />
                <stop offset="100%" stopColor={color} stopOpacity={0.08} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: '#999' }}
              axisLine={{ stroke: '#222' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#999' }}
              axisLine={false}
              tickLine={false}
              width={30}
            />
            <Tooltip
              contentStyle={{
                background: '#161616',
                border: '1px solid #2a2a2a',
                borderRadius: 4,
                fontSize: 11,
                color: '#d9d9d9',
              }}
            />
            <Bar
              dataKey="count"
              fill={`url(#${gradientId})`}
              stroke={color}
              strokeOpacity={0.4}
              radius={[2, 2, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
```

Key changes from previous:
- Added `<defs>` with `<linearGradient>` using the chart color at 0.25→0.08 opacity
- Bar uses `fill={url(#gradient)}` + `stroke` with 0.4 opacity
- XAxis/YAxis tick fontSize 9→11, fill `#555`→`#999`

- [ ] **Step 2: Verify in browser**

Open the app, navigate to a dataset's Overview tab. Confirm:
- Bar charts show ghost gradient fill (transparent, lighter at top) with colored border
- Axis labels are larger and more readable (11px, #999 color)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/OverviewTab.tsx
git commit -m "feat: ghost gradient chart bars and improved axis text"
```

---

### Task 3: Episode Length Time Labels

**Files:**
- Modify: `frontend/src/components/OverviewTab.tsx`

- [ ] **Step 1: Add compact duration formatter**

In `frontend/src/components/OverviewTab.tsx`, add after the existing `formatDuration` function (after line 118):

```typescript
function formatCompactDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = Math.floor(totalSeconds % 60)
  if (hours > 0) return `${hours}h${minutes}m`
  if (minutes > 0) return `${minutes}m${secs}s`
  return `${secs}s`
}
```

- [ ] **Step 2: Add fps prop to ChartPanel and time label formatter**

Update ChartPanel to accept optional `fps` and format length labels:

```tsx
function ChartPanel({ chart, color, fps }: { chart: DistributionResult; color: string; fps?: number }) {
  const gradientId = `gradient-${chart.field}`

  const formatLabel = (label: string) => {
    if (!fps || chart.field !== 'length') return label
    const parts = label.split('-').map(Number)
    if (parts.length !== 2 || parts.some(isNaN)) return label
    return `${formatCompactDuration(parts[0] / fps)}-${formatCompactDuration(parts[1] / fps)}`
  }
```

Update the XAxis to use the formatter:

```tsx
<XAxis
  dataKey="label"
  tick={{ fontSize: 11, fill: '#999' }}
  axisLine={{ stroke: '#222' }}
  tickLine={false}
  tickFormatter={formatLabel}
/>
```

- [ ] **Step 3: Pass fps to ChartPanel for length chart**

In the `OverviewTab` component, update the ChartPanel rendering (around line 92):

```tsx
{otherCharts.map((chart, idx) => (
  <ChartPanel
    key={chart.field}
    chart={chart}
    color={CHART_COLORS[idx % CHART_COLORS.length]}
    fps={chart.field === 'length' ? fps : undefined}
  />
))}
```

- [ ] **Step 4: Verify in browser**

Open overview tab for a dataset. The Episode Length histogram should now show time labels like "1m20s-2m40s" instead of frame numbers like "2400-4800".

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/OverviewTab.tsx
git commit -m "feat: display episode length in time units"
```

---

### Task 4: Clickable Charts → Curate Navigation

**Files:**
- Modify: `frontend/src/components/OverviewTab.tsx`
- Modify: `frontend/src/components/DatasetPage.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Add onNavigateCurate prop to OverviewTab**

In `frontend/src/components/OverviewTab.tsx`, update the interface and component:

```typescript
import type { CurateFilter, DistributionResult, Episode } from '../types'

interface OverviewTabProps {
  datasetPath: string
  fps: number
  episodes: Episode[]
  onNavigateCurate: (filter: CurateFilter) => void
}

export function OverviewTab({ datasetPath, fps, episodes, onNavigateCurate }: OverviewTabProps) {
```

- [ ] **Step 2: Make GradeSummary cards clickable**

Update the `GradeSummary` function signature to accept the callback:

```tsx
function GradeSummary({ chart, fps, episodes, onNavigateCurate }: {
  chart: DistributionResult
  fps: number
  episodes: Episode[]
  onNavigateCurate: (filter: CurateFilter) => void
}) {
```

Update each grade card `<div>` (the one with `key={item.key}`, around line 157) to add click handler and hover style:

```tsx
<div key={item.key} style={{
  background: item.bg,
  border: `1px solid ${count > 0 ? item.color : 'var(--border)'}`,
  borderRadius: 8,
  padding: '12px 10px',
  textAlign: 'center',
  cursor: 'pointer',
  transition: 'transform 0.15s, border-color 0.15s',
}}
  onClick={() => onNavigateCurate({ grade: item.key === '(ungraded)' ? 'ungraded' : item.key })}
  onMouseEnter={e => {
    (e.currentTarget as HTMLElement).style.transform = 'scale(1.02)'
    ;(e.currentTarget as HTMLElement).style.borderColor = item.color
  }}
  onMouseLeave={e => {
    (e.currentTarget as HTMLElement).style.transform = 'scale(1)'
    ;(e.currentTarget as HTMLElement).style.borderColor = count > 0 ? item.color : 'var(--border)'
  }}
>
```

Pass the callback to GradeSummary in the render:

```tsx
{gradeChart && <GradeSummary chart={gradeChart} fps={fps} episodes={episodes} onNavigateCurate={onNavigateCurate} />}
```

- [ ] **Step 3: Make ChartPanel bars clickable for length and tags**

Add `onBarClick` prop to ChartPanel:

```tsx
function ChartPanel({ chart, color, fps, onBarClick }: {
  chart: DistributionResult
  color: string
  fps?: number
  onBarClick?: (label: string) => void
}) {
```

Update the `<Bar>` element to handle clicks:

```tsx
<Bar
  dataKey="count"
  fill={`url(#${gradientId})`}
  stroke={color}
  strokeOpacity={0.4}
  radius={[2, 2, 0, 0]}
  cursor={onBarClick ? 'pointer' : undefined}
  onClick={onBarClick ? (data: { label?: string }) => {
    if (data.label) onBarClick(data.label)
  } : undefined}
  activeBar={onBarClick ? { strokeOpacity: 0.8 } : undefined}
/>
```

- [ ] **Step 4: Wire click handlers in OverviewTab render**

Update the ChartPanel rendering in `OverviewTab` to pass `onBarClick` for length and tags:

```tsx
{otherCharts.map((chart, idx) => {
  let onBarClick: ((label: string) => void) | undefined
  if (chart.field === 'length') {
    onBarClick = (label: string) => {
      const parts = label.split('-').map(Number)
      if (parts.length === 2 && parts.every(n => !isNaN(n))) {
        onNavigateCurate({ lengthRange: [parts[0], parts[1]] })
      }
    }
  } else if (chart.field === 'tags') {
    onBarClick = (label: string) => {
      if (label !== '(no tags)') onNavigateCurate({ tag: label })
    }
  }
  return (
    <ChartPanel
      key={chart.field}
      chart={chart}
      color={CHART_COLORS[idx % CHART_COLORS.length]}
      fps={chart.field === 'length' ? fps : undefined}
      onBarClick={onBarClick}
    />
  )
})}
```

- [ ] **Step 5: Pass onNavigateCurate from DatasetPage**

In `frontend/src/components/DatasetPage.tsx`, update the OverviewTab rendering (around line 108-114):

```tsx
if (tab === 'overview') {
  return (
    <div className="dataset-page">
      <OverviewTab
        datasetPath={datasetPath}
        fps={dataset?.fps ?? 30}
        episodes={episodes}
        onNavigateCurate={(f) => onSetTab('curate', f)}
      />
    </div>
  )
}
```

- [ ] **Step 6: Verify in browser**

- Open overview tab
- Hover over a Grade card → should scale slightly, border brightens
- Click "Good" card → should navigate to Curate tab
- Click a bar in the Episode Length histogram → should navigate to Curate tab
- Click a bar in Tags chart → should navigate to Curate tab

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/OverviewTab.tsx frontend/src/components/DatasetPage.tsx
git commit -m "feat: clickable overview charts navigate to curate tab"
```

---

### Task 5: Filter Chips + Episode Filtering in Curate

**Files:**
- Modify: `frontend/src/components/DatasetPage.tsx`
- Modify: `frontend/src/components/EpisodeList.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Add episode filtering in DatasetPage**

In `frontend/src/components/DatasetPage.tsx`, add the `formatDuration` helper at the top of the file (after imports):

```typescript
function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const secs = Math.floor(totalSeconds % 60)
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`
  if (minutes > 0) return `${minutes}m ${secs}s`
  return `${secs}s`
}
```

Inside the `DatasetPage` component, add the filtering logic before the curate layout return (after the `useEffect` and keyboard handler blocks):

```typescript
const fps = dataset?.fps ?? 30

const curateEpisodes = useMemo(() => {
  let result = episodes
  if (filter?.lengthRange) {
    const [min, max] = filter.lengthRange
    result = result.filter(e => e.length >= min && e.length < max)
  }
  if (filter?.tag) {
    result = result.filter(e => e.tags.includes(filter.tag!))
  }
  return result
}, [episodes, filter])

const filterChip = useMemo(() => {
  if (filter?.lengthRange) {
    const [min, max] = filter.lengthRange
    return {
      label: `Length: ${formatDuration(min / fps)} ~ ${formatDuration(max / fps)}`,
      onClear: () => onSetTab('curate'),
    }
  }
  if (filter?.tag) {
    return {
      label: `Tag: ${filter.tag}`,
      onClear: () => onSetTab('curate'),
    }
  }
  return null
}, [filter, fps, onSetTab])
```

- [ ] **Step 2: Pass filtered episodes and chip to EpisodeList**

Update the `EpisodeList` usage in the curate layout. Replace `episodes` with `curateEpisodes` and add new props:

```tsx
<EpisodeList
  episodes={curateEpisodes}
  loading={epLoading}
  error={epError}
  onEpisodeSelect={setSelectedEpisode}
  selectedIndex={selectedEpisode?.episode_index ?? null}
  initialGradeFilter={filter?.grade ?? undefined}
  filterChip={filterChip}
/>
```

Also update `ungradedEpisodes` to use `curateEpisodes`:

```typescript
const ungradedEpisodes = useMemo(() => curateEpisodes.filter(e => !e.grade), [curateEpisodes])
```

And update episode navigation to use `curateEpisodes`:

```typescript
const navigateEpisode = useCallback((direction: -1 | 1) => {
  if (!selectedEpisode || curateEpisodes.length === 0) return
  const idx = curateEpisodes.findIndex(e => e.episode_index === selectedEpisode.episode_index)
  const next = curateEpisodes[idx + direction]
  if (next) setSelectedEpisode(next)
}, [selectedEpisode, curateEpisodes])
```

Update `quickGrade` to reference `curateEpisodes` if needed (for tag finding in handleSaveEpisode, keep using `episodes` since we save across the full dataset):

In `handleSaveEpisode`, update the ungraded-advance logic to use `curateEpisodes`:

```typescript
const handleSaveEpisode = useCallback(async (index: number, grade: string | null, tags: string[]) => {
  await updateEpisode(index, grade, tags)
  if (grade) {
    const currentIdx = curateEpisodes.findIndex(e => e.episode_index === index)
    const ungradedInView = curateEpisodes.filter(e => !e.grade)
    const nextUngraded = ungradedInView.find(e => {
      const i = curateEpisodes.indexOf(e)
      return i > currentIdx
    }) ?? ungradedInView.find(e => {
      const i = curateEpisodes.indexOf(e)
      return i < currentIdx
    })
    if (nextUngraded) {
      setSelectedEpisode(nextUngraded)
      return
    }
  }
  setSelectedEpisode(prev =>
    prev?.episode_index === index ? { ...prev, grade, tags } : prev
  )
}, [updateEpisode, curateEpisodes])
```

- [ ] **Step 3: Update EpisodeList to accept filter chip and initial grade**

In `frontend/src/components/EpisodeList.tsx`, update the interface and component:

```typescript
interface EpisodeListProps {
  episodes: Episode[]
  loading: boolean
  error: string | null
  onEpisodeSelect: (episode: Episode) => void
  selectedIndex: number | null
  initialGradeFilter?: GradeFilter
  filterChip?: { label: string; onClear: () => void } | null
}
```

Update the component to use the new props:

```tsx
export const EpisodeList = memo(function EpisodeList({
  episodes, loading, error, onEpisodeSelect, selectedIndex,
  initialGradeFilter, filterChip,
}: EpisodeListProps) {
  const [gradeFilter, setGradeFilter] = useState<GradeFilter>(initialGradeFilter ?? 'all')
```

Add the filter chip rendering after the header and before the grade filter bar:

```tsx
<div className="episode-sidebar-header">
  <span className="episode-sidebar-title">Episodes</span>
  <span className="episode-progress-count">{gradedCount} / {episodes.length}</span>
</div>

{filterChip && (
  <div className="filter-chip-bar">
    <span className="filter-chip">
      {filterChip.label}
      <button className="filter-chip-clear" onClick={filterChip.onClear}>&times;</button>
    </span>
  </div>
)}

<div className="grade-filter-bar">
```

- [ ] **Step 4: Add filter chip CSS**

In `frontend/src/App.css`, add after the `.grade-filter-bar` styles (search for `grade-filter` to find the right location):

```css
/* ── Filter chip ─────────────────────────────── */
.filter-chip-bar {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--interactive-dim);
  border: 1px solid rgba(137, 180, 250, 0.3);
  border-radius: 12px;
  padding: 2px 6px 2px 8px;
  font-size: 10px;
  color: var(--interactive);
}
.filter-chip-clear {
  background: none;
  border: none;
  color: var(--interactive);
  opacity: 0.6;
  font-size: 12px;
  padding: 0 2px;
  cursor: pointer;
  line-height: 1;
}
.filter-chip-clear:hover {
  opacity: 1;
}
```

- [ ] **Step 5: Verify full flow in browser**

Test each scenario:
1. Overview → click "Good" card → Curate shows with grade filter on "Good", episodes filtered
2. Overview → click a bar in Episode Length histogram → Curate shows with chip "Length: Xm Ys ~ Am Bs", only episodes in that range
3. Overview → click a bar in Tags chart → Curate shows with chip "Tag: pick", only episodes with that tag
4. Click X on filter chip → chip disappears, all episodes show
5. Grade filter buttons still work independently alongside length/tag chips

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DatasetPage.tsx frontend/src/components/EpisodeList.tsx frontend/src/App.css
git commit -m "feat: filter chips and episode filtering in curate tab"
```

---

### Verification Checklist

After all tasks are complete, verify the full feature set:

- [ ] Grade cards on Overview are clickable with hover effect (scale + border)
- [ ] Clicking Grade card navigates to Curate with correct grade filter active
- [ ] Episode Length histogram bars are clickable (cursor: pointer)
- [ ] Clicking Length bar navigates to Curate with length chip showing time range
- [ ] Tags chart bars are clickable
- [ ] Clicking Tag bar navigates to Curate with tag chip
- [ ] Filter chips display correctly with X button
- [ ] Clicking chip X clears the filter
- [ ] Grade filter buttons in Curate work alongside length/tag chips
- [ ] Chart bars show ghost gradient (transparent gradient fill + colored border)
- [ ] Chart axis text is readable (11px, #999)
- [ ] Episode Length histogram shows time labels (e.g., "1m20s-2m40s")
- [ ] Non-clickable charts (task_instruction, collection_date) have no pointer cursor
