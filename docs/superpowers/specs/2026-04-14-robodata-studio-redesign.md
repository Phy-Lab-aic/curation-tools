# robodata-studio — 전면 리디자인 설계 문서

**날짜:** 2026-04-14  
**현재 저장소:** `curation-tools`  
**제안 저장소 이름:** `robodata-studio`  
**대상:** 로봇/ML 연구원 + 데이터 엔지니어 (사내 내부 도구)

---

## 1. 목표

LeRobot v3.0 포맷 기반의 로봇 데이터셋을 위한 사내 큐레이션 + 분석 UI로 전환한다.

- 20개 이상의 마운트된 데이터셋을 셀(물리적 로봇 스테이션) 단위로 탐색
- 에피소드 그레이딩(큐레이션) 워크플로 유지
- 사용자가 선택한 필드 기반 데이터 분포 시각화
- `meta/info.json` 및 `meta/episodes/*.parquet` 커스텀 필드 추가
- 기존 변환기(ConversionPage), HubSync 전부 제거

---

## 2. 저장소 이름

**`robodata-studio`** — 범용적이며 기능을 명확히 전달. LeRobot 포맷 전용이지만 외부 공개 시에도 자연스러운 이름.

---

## 3. 네비게이션 계층 (3단계)

```
Library (홈)
  └── Cell (물리적 로봇 스테이션 — 마운트 경로에서 cell* 패턴으로 자동 파싱)
        └── Dataset (LeRobot v3.0 데이터셋)
              ├── Overview 탭   ← 신규: 분포 시각화
              ├── Curate 탭     ← 기존 유지 + 리디자인
              ├── Fields 탭     ← 신규: 필드 추가/편집
              └── Ops 탭        ← 기존 유지 (Split/Merge/Export)
```

**URL 구조 (React Router 없이 상태 기반):**
- 앱 상태: `page: 'library' | 'cell' | 'dataset'`
- 선택된 cell, dataset, tab을 상태로 관리
- React Router 미도입 (공수 절감, 단일 SPA로 충분)

**Cell 파싱 규칙:**
- `allowed_dataset_roots` 의 각 경로를 스캔
- 직접 자식 디렉토리 중 `cell*` 패턴에 매칭되는 것 → Cell
- Cell 내부에서 `meta/info.json` 존재하면 Dataset

---

## 4. 비주얼 디자인 시스템

### 4.1 팔레트

Grafana 스타일 — 순수 블랙 베이스, UI 크롬은 거의 무채색, 데이터만 비비드.

| 토큰 | 값 | 용도 |
|---|---|---|
| `--bg` | `#0f0f0f` | 앱 전체 배경 |
| `--panel` | `#161616` | 패널/카드 배경 |
| `--panel2` | `#1c1c1c` | 중첩 패널, hover |
| `--border` | `#222222` | 주요 구분선 |
| `--border2` | `#2a2a2a` | 보조 구분선 |
| `--text` | `#d9d9d9` | 주요 텍스트 |
| `--text-muted` | `#555555` | 보조 텍스트 |
| `--text-dim` | `#333333` | 비활성 텍스트 |
| `--accent` | `#ff9830` | 선택/활성 상태, CTA |

### 4.2 데이터 컬러

차트 시리즈 및 상태 표시 전용. UI 크롬에는 사용하지 않음.

| 토큰 | 값 | 용도 |
|---|---|---|
| `--c-green` | `#73bf69` | good 등급, 완료 상태 |
| `--c-yellow` | `#fade2a` | normal 등급, 경고 |
| `--c-red` | `#f08080` | bad 등급, 오류 |
| `--c-blue` | `#5794f2` | 데이터 시리즈 1 |
| `--c-purple` | `#b877d9` | 데이터 시리즈 2 |
| `--c-orange` | `#ff9830` | 데이터 시리즈 3 (accent와 동일) |

### 4.3 Grade UI (D1 — 언더라인 탭)

```
[ good ]  normal  bad          [1] [2] [3]
  ────
```

- 활성 상태: 텍스트 밝게 (`--text`) + 하단 2px 언더라인 (`--text`)
- 비활성: `--text-dim`
- 색상 없음 — 색은 에피소드 목록의 grade 점(●)에서만 사용
- 키보드 단축키 `1` `2` `3` 항상 표시

### 4.4 공통 컴포넌트 규칙

- 모든 탭 페이지는 동일한 `<TopNav>` 공유 (로고 + breadcrumb + 탭바)
- 카드/패널: `--panel` 배경 + `--border` 1px 테두리 + 6~8px border-radius
- 버튼: 기본 `--panel2` + `--border2`. CTA만 `--accent`
- 폰트: `-apple-system, BlinkMacSystemFont, 'Inter', sans-serif`
- 숫자/코드: `monospace`

---

## 5. 페이지별 설계

### 5.1 Library 페이지 (홈)

**레이아웃:** 상단 검색/필터 바 + 셀 목록

- 마운트 경로별로 그룹핑된 **Cell 카드 그리드**
- Cell 카드: 이름, 로봇 타입, 데이터셋 수, 활성 상태(마운트 여부)
- 검색: 데이터셋 이름 텍스트 검색
- 필터 칩: 로봇 타입별 (`ur5e`, `so100`, `panda` 등)

**Cell 카드 클릭 → Cell 페이지:**
- Cell 내 데이터셋 목록 (카드 그리드)
- 데이터셋 카드: 이름, 에피소드 수, FPS, 큐레이션 진행률 바, grade 분포 세그먼트

### 5.2 Overview 탭 (신규)

**레이아웃:** 좌측 필드 선택 패널 + 우측 패널 그리드

**필드 선택 패널:**
- 3개 섹션: 메타데이터 / Parquet 컬럼 / 커스텀 필드
- 체크박스로 필드 선택
- "차트 추가" 버튼 → 백엔드 집계 요청

**패널 그리드:**
- W&B 스타일 — 추가/제거 가능한 독립 위젯
- 상단 고정: Stats Bar (총 에피소드 수, 그레이딩된 수, 미그레이딩, 태스크 수)
- 차트 유형 자동 추천: `int/float` → Histogram, `str/category` → Bar/Donut
- 차트 유형 드롭다운으로 수동 변경 가능

**성능:** pyarrow column projection으로 선택된 컬럼만 읽음

### 5.3 Curate 탭 (기존 유지 + 리디자인)

**레이아웃:** 3컬럼 (에피소드 목록 | 비디오+grade | 스칼라+상세)

**에피소드 목록 (좌측):**
- 진행률 카운터 (`92 / 142`)
- 각 행: grade 색상 점(●) + 에피소드 인덱스 + 프레임 수
- 활성 항목: 좌측 `--accent` 2px 보더 + `--accent-dim` 배경

**비디오 플레이어 (중앙):**
- 기존 VideoPlayer 컴포넌트 유지, 스타일만 통일
- 하단 스크러버 바: `--accent` 색
- Terminal frames 바 유지
- Grade 바 (D1 스타일): `good / normal / bad` 언더라인 탭

**스칼라 + 상세 (우측):**
- 탭: Details | Split/Merge
- Details: 에피소드 정보 + 태그 + 스칼라 차트
- 스칼라 차트: 시리즈마다 `--c-*` 비비드 컬러 할당

### 5.4 Fields 탭 (신규)

**좌측 네비:** Dataset Info | Episode Columns

**Dataset Info (info.json):**
- 시스템 필드: 읽기 전용 표시
- 커스텀 필드: 편집/삭제 가능
- 신규 필드 추가 폼: key, 타입(string/number/boolean), 기본값

**Episode Columns (meta/episodes/*.parquet):**
- 기존 컬럼: 읽기 전용
- 커스텀 컬럼: 삭제 가능
- 신규 컬럼 추가: key, 타입, 기본값
- ⚠ 경고: 전체 parquet 파일 재작성 필요 (대용량 시 소요 시간 안내)

### 5.5 Ops 탭 (기존 유지)

- SplitMergePanel 컴포넌트 그대로 유지
- Export (grade 기반 필터링) 유지
- 스타일만 통일

---

## 6. 백엔드 변경사항

### 6.1 제거

| 파일 | 이유 |
|---|---|
| `backend/routers/conversion.py` | 변환기 기능 전체 제거 |
| `backend/services/conversion_service.py` | 동일 |
| `backend/routers/hf_sync.py` | HubSync 제거 |
| `backend/services/hf_sync_service.py` | 동일 |

### 6.2 신규 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/cells` | 마운트 경로 스캔 → `cell*` 패턴 셀 목록 반환 |
| `GET` | `/api/cells/{cell}/datasets` | 셀 내 데이터셋 목록 (진행률 포함) |
| `POST` | `/api/datasets/distribution` | 선택 필드 집계 → 분포 데이터 반환 |
| `PATCH` | `/api/datasets/info-fields` | `meta/info.json` 커스텀 필드 추가/수정 |
| `POST` | `/api/datasets/episode-columns` | `meta/episodes/*.parquet` 컬럼 추가 |

### 6.3 유지

- `datasets`, `episodes`, `tasks`, `videos`, `scalars`, `dataset_ops`, `rerun` 라우터 전부 유지
- `dataset_service`, `episode_service`, `export_service`, `dataset_ops_service` 유지

### 6.4 config 변경

```python
# 기존
allowed_dataset_roots: list[str] = [...]

# 추가: cell 파싱 패턴 (기본값으로 충분, 필요시 오버라이드)
cell_name_pattern: str = "cell*"
```

---

## 7. 프론트엔드 변경사항

### 7.1 제거

- `src/components/ConversionPage.tsx`
- `src/components/conversion/ConfigPanel.tsx`
- `src/components/conversion/StatusPanel.tsx`
- `src/hooks/useConversion.ts`
- `src/components/HubSync.tsx`
- `App.tsx`의 page-tab-bar (Conversion/Curation 전환)

### 7.2 신규

- `src/components/LibraryPage.tsx` — Cell 그리드 홈
- `src/components/CellPage.tsx` — 셀 내 데이터셋 목록
- `src/components/DatasetPage.tsx` — 탭 컨테이너
- `src/components/OverviewTab.tsx` — 분포 시각화
- `src/components/FieldsTab.tsx` — 필드 편집기
- `src/components/TopNav.tsx` — 공통 상단 네비게이션
- `src/hooks/useCells.ts`
- `src/hooks/useDistribution.ts`
- `src/hooks/useFields.ts`

### 7.3 유지 (스타일 통일)

- `EpisodeList`, `VideoPlayer`, `ScalarChart`
- `EpisodeEditor`, `TaskEditor`
- `SplitMergePanel`
- `useEpisodes`, `useDataset`

### 7.4 CSS 변수 시스템

기존 Catppuccin 하드코딩 색상을 CSS 변수로 전환:

```css
:root {
  --bg: #0f0f0f;
  --panel: #161616;
  --panel2: #1c1c1c;
  --border: #222;
  --border2: #2a2a2a;
  --text: #d9d9d9;
  --text-muted: #555;
  --text-dim: #333;
  --accent: #ff9830;
  --c-green: #73bf69;
  --c-yellow: #fade2a;
  --c-red: #f08080;
  --c-blue: #5794f2;
  --c-purple: #b877d9;
}
```

---

## 8. 구현 우선순위

1. **Phase 1 — 기반 정리:** 제거 대상 코드 삭제 + CSS 변수 시스템 도입 + TopNav 컴포넌트
2. **Phase 2 — 네비게이션:** Library → Cell → Dataset 3단계 라우팅 + 백엔드 `/api/cells`
3. **Phase 3 — Curate 리디자인:** 기존 큐레이션 페이지를 새 팔레트로 통일 (D1 grade UI 포함)
4. **Phase 4 — Overview 탭:** 분포 시각화 + `/api/datasets/distribution` 엔드포인트
5. **Phase 5 — Fields 탭:** 필드 편집기 + `/api/datasets/info-fields`, `/api/datasets/episode-columns`
