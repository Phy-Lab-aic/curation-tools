# Overview Chart Interaction + Visual Improvements

**Date:** 2026-04-15
**Status:** Approved

## Summary

Overview 탭의 차트를 클릭하면 Curate 탭으로 이동하면서 해당 조건으로 필터링된 에피소드를 보여주는 기능 추가. 동시에 차트 시각 디자인 개선 (색상, 텍스트, 시간 단위).

## Features

### F1. Grade Card Click → Curate with Grade Filter

- **동작:** GradeSummary의 Good/Normal/Bad/Ungraded 카드 클릭 시 Curate 탭으로 이동
- **필터 적용:** EpisodeList의 기존 `gradeFilter` 상태를 외부에서 프리셋
- **구현 방향:**
  - `AppState`의 dataset 뷰에 optional `filter` 필드 추가
  - `setTab('curate', { grade: 'good' })` 형태의 호출
  - `DatasetPage`에서 `filter.grade`를 `EpisodeList`에 prop으로 전달
  - `EpisodeList`의 `gradeFilter` 초기값을 prop에서 받도록 변경

### F2. Episode Length Histogram Bar Click → Curate with Length Range Filter

- **동작:** Episode Length 히스토그램의 바 클릭 시 Curate 탭으로 이동
- **필터 적용:** 해당 바의 length 범위(프레임 단위)에 속하는 에피소드만 표시
- **구현 방향:**
  - 차트 바 클릭 이벤트에서 bin의 range 정보 추출
  - `setTab('curate', { lengthRange: [minFrames, maxFrames] })` 호출
  - `DatasetPage`에서 `filter.lengthRange`로 에피소드 필터링 후 `EpisodeList`에 전달

### F3. Tags Bar Chart Click → Curate with Tag Filter

- **동작:** Tags 차트의 바 클릭 시 Curate 탭으로 이동
- **필터 적용:** 해당 태그를 가진 에피소드만 표시
- **구현 방향:**
  - 차트 바 클릭 이벤트에서 tag label 추출
  - `setTab('curate', { tag: 'pick' })` 호출
  - `DatasetPage`에서 `filter.tag`로 에피소드 필터링 후 `EpisodeList`에 전달

### F4. Filter Chip Display in Curate

- **위치:** EpisodeList 상단, grade 필터 바 위
- **표시:** `Length: 3m~5m ×` 또는 `Tag: pick ×` 형태의 칩
- **해제:** X 버튼 클릭 시 필터 해제, 전체 에피소드 목록으로 복귀
- **Grade 필터:** 기존 grade 필터 버튼을 그대로 활용 (chip 불필요)
- **조합:** length/tag 칩과 grade 필터는 독립적으로 조합 가능

## Visual Changes

### V1. Chart Color: Ghost Gradient + Border

기존 solid fill을 반투명 그라디언트 + 색상 테두리로 변경.

- **fill:** `linear-gradient(to top, rgba(color, 0.25), rgba(color, 0.08))`
- **border:** `1px solid rgba(color, 0.4)` (하단 제외)
- **hover:** opacity 소폭 증가 (0.25 → 0.4)
- **적용 대상:** OverviewTab의 모든 ChartPanel 바 차트
- **recharts 구현:** `<defs>` + `<linearGradient>` 사용, Bar에 `fill="url(#gradient-{idx})"` + `stroke` 속성

### V2. Chart Axis Text Size Increase

- **XAxis tick:** fontSize 9 → 11, fill `#555` → `#999` (var(--text-muted))
- **YAxis tick:** fontSize 9 → 11, fill `#555` → `#999`
- 다크 배경에서 가독성 확보

### V3. Episode Length Time Unit Display

히스토그램 bin 라벨을 프레임 수 대신 시간으로 표시.

- **변환 위치:** 프론트엔드 (백엔드는 프레임 단위 유지)
- **변환 로직:** `frames / fps` → 초 → `formatDuration()` 함수로 포맷
- **표시 형식:** `3m 20s`, `1h 2m` 등
- **fps 전달:** OverviewTab에서 ChartPanel으로 fps prop 전달 (length 차트에만)
- **범위 라벨:** `3m 20s ~ 6m 40s` 형태

### V4. Clickable Visual Cues

클릭 가능한 차트 요소에 인터랙션 힌트 추가.

- **차트 바:** `cursor: pointer`, hover 시 밝기 증가
- **Grade 카드:** `cursor: pointer`, hover 시 border 색상 강조 + scale(1.02) 미세 확대
- **클릭 불가 차트:** task_instruction, collection_date 등은 기존 스타일 유지

## Architecture

### State Changes

```typescript
// types/index.ts - AppState 확장
interface CurateFilter {
  grade?: string        // 'good' | 'normal' | 'bad' | 'ungraded'
  lengthRange?: [number, number]  // [minFrames, maxFrames]
  tag?: string
}

type AppState =
  | { view: 'library' }
  | { view: 'cell'; cellName: string; cellPath: string }
  | { view: 'dataset'; cellName: string; cellPath: string; datasetPath: string; datasetName: string; tab: DatasetTab; filter?: CurateFilter }
  | { view: 'converter' }
```

### Data Flow

```
OverviewTab (chart click)
  → setTab('curate', { grade: 'good' })
  → useAppState updates state.tab + state.filter
  → DatasetPage reads filter, passes to EpisodeList
  → EpisodeList applies filter + shows chip
  → User clicks chip X → filter cleared
```

### Component Changes

| Component | Changes |
|-----------|---------|
| `types/index.ts` | `CurateFilter` 타입 추가, `AppState` 확장 |
| `useAppState.ts` | `setTab` 시그니처 확장 (filter 옵션) |
| `OverviewTab.tsx` | GradeSummary/ChartPanel에 onClick 핸들러, fps prop 전달, gradient 색상 |
| `DatasetPage.tsx` | filter prop 전달, length/tag 기반 에피소드 필터링 |
| `EpisodeList.tsx` | filter chip UI, 외부 filter prop 수신, gradeFilter 초기값 연동 |
| `App.css` | filter-chip 스타일, chart hover 스타일, gradient bar 스타일 |

## Scope Boundaries

- grade, length, tags 차트만 클릭 가능 (task_instruction, collection_date는 추후)
- 백엔드 변경 없음 (프론트엔드만)
- 멀티 필터 조합은 grade + (length 또는 tag) 수준 (length + tag 동시는 미지원)
