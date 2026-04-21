# Converter 진행 상태 표시 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert 페이지 각 task 카드에 Converting / Finalizing / Done 상태를 뱃지 + 바 애니메이션으로 명시 표시해서, 긴 녹화 변환 중이나 finalize 단계에서도 "살아 있다"가 명확히 보이게 한다.

**Architecture:** `auto_converter`에 `Finalizing:` 로그 1줄을 추가하고, 백엔드 파서가 이를 구조화된 이벤트(`finalizing`, `finalized`)로 분리한다. 프론트는 `ConverterPage`가 WebSocket을 구독해서 자식 컴포넌트(`ConverterProgress`, `ConverterLogs`) 둘 다에 이벤트를 내려주고, `ConverterProgress`는 이벤트에서 task별 liveStatus를 유도해 카드에 뱃지/애니메이션을 입힌다. `/status` 10초 폴링은 그대로 유지하여 `done/total` 숫자의 진실의 원천 역할을 한다.

**Tech Stack:** Python 3 / pytest · FastAPI WebSocket · React 18 + TypeScript · CSS (keyframes)

**Spec:** `docs/superpowers/specs/2026-04-21-converter-progress-status-design.md`

**File structure (새로 만들지 않고 기존 파일 수정):**
- `rosbag2lerobot-svt/auto_converter.py` — finalize 진입 로그 1줄
- `rosbag2lerobot-svt/test/test_auto_converter.py` — finalize 로그 순서 검증 추가
- `backend/converter/router.py` — 정규식 2개 + 분기 2개
- `tests/test_converter_router.py` — `finalizing` / `finalized` 파싱 케이스 추가
- `frontend/src/types/index.ts` — `LogEventType` 확장
- `frontend/src/components/ConverterPage.tsx` — WS 구독 호스팅, events 공유
- `frontend/src/components/ConverterLogs.tsx` — WS 로직 제거 + events prop, EventRow 케이스 추가
- `frontend/src/components/ConverterProgress.tsx` — events prop + taskLive 유도 + 뱃지/애니메이션 렌더
- `frontend/src/App.css` — 상태 뱃지, shimmer, pulse, reduced-motion

---

## Task 1: 백엔드 파서에 finalizing / finalized 분기 추가 (TDD)

**Files:**
- Test: `tests/test_converter_router.py`
- Modify: `backend/converter/router.py:40-115`

- [ ] **Step 1: 실패하는 파서 테스트 3개 추가**

`tests/test_converter_router.py` 파일 끝에 append:

```python
def test_parse_finalizing_line():
    event = _parse_log_line(
        "2026-04-21 12:34:56 [INFO]   Finalizing: cell001/pick_and_place",
    )

    assert event == {
        "type": "finalizing",
        "ts": "2026-04-21 12:34:56",
        "task": "cell001/pick_and_place",
    }


def test_parse_finalized_line():
    event = _parse_log_line(
        "2026-04-21 12:35:12 [INFO]   Finalized: cell001/pick_and_place",
    )

    assert event == {
        "type": "finalized",
        "ts": "2026-04-21 12:35:12",
        "task": "cell001/pick_and_place",
    }


def test_parse_finalizing_line_with_three_level_task():
    event = _parse_log_line(
        "2026-04-21 12:34:56 [INFO]   Finalizing: cell001/outer/inner",
    )

    assert event == {
        "type": "finalizing",
        "ts": "2026-04-21 12:34:56",
        "task": "cell001/outer/inner",
    }
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_converter_router.py::test_parse_finalizing_line tests/test_converter_router.py::test_parse_finalized_line tests/test_converter_router.py::test_parse_finalizing_line_with_three_level_task -v
```

Expected: 3개 FAIL. 기존에는 `Finalizing:` 라인이 generic `info` 이벤트로 떨어지거나 noise 필터로 걸러져 `None` 반환.

- [ ] **Step 3: 파서에 정규식 2개 + 분기 2개 추가**

`backend/converter/router.py` 에서 기존 정규식 블록(`_CONVERTING_RE` 아래)에 두 개 추가:

```python
_FINALIZING_RE = re.compile(
    r"Finalizing:\s+(.+)$"
)
_FINALIZED_RE = re.compile(
    r"Finalized:\s+(.+)$"
)
```

`_parse_log_line` 함수에서 `scan_m` 분기 **바로 앞**에 두 분기 추가:

```python
finalizing_m = _FINALIZING_RE.search(msg)
if finalizing_m:
    return {
        "type": "finalizing", "ts": ts,
        "task": finalizing_m.group(1).strip(),
    }

finalized_m = _FINALIZED_RE.search(msg)
if finalized_m:
    return {
        "type": "finalized", "ts": ts,
        "task": finalized_m.group(1).strip(),
    }
```

배치 순서가 중요: `_CONVERTED_RE`(Converted:) / `_FAILED_RE` / `_CONVERTING_RE` 아래, `_SCAN_RE` 분기 위. 이 위치여야 `Converted:`와 `Converting:` 이 우선 매칭돼도 문제없고, finalize 쌍만 새 분기가 잡는다.

- [ ] **Step 4: 전체 파서 테스트 재실행**

```bash
pytest tests/test_converter_router.py -v
```

Expected: 5개 모두 PASS (기존 2 + 신규 3). `test_parse_converted_line_*` 회귀 없음.

- [ ] **Step 5: Commit**

```bash
git add tests/test_converter_router.py backend/converter/router.py
git commit -m "feat(converter): parse Finalizing/Finalized log lines as structured events"
```

---

## Task 2: auto_converter에 Finalizing 로그 추가 (TDD)

**Files:**
- Test: `rosbag2lerobot-svt/test/test_auto_converter.py`
- Modify: `rosbag2lerobot-svt/auto_converter.py:262-277`

- [ ] **Step 1: 실패하는 테스트 추가**

먼저 기존 테스트 파일 구조 확인:

```bash
sed -n '48,120p' rosbag2lerobot-svt/test/test_auto_converter.py
```

파일 하단에 새 테스트 함수 append. 기존 `_FakeCreator` 등을 재사용한다:

```python
def test_convert_task_logs_finalizing_before_finalize(tmp_path, caplog, monkeypatch):
    """`Finalizing:` 로그가 creator.finalize() 호출 직전에 찍혀야 한다."""
    import logging

    raw_base = tmp_path / "raw"
    lerobot_base = tmp_path / "lerobot"
    lerobot_base.mkdir()
    _write_raw_recording(raw_base, "cell001", "pick_task", "20260421_120000")

    monkeypatch.setattr(auto_converter, "RAW_BASE", raw_base)
    monkeypatch.setattr(auto_converter, "LEROBOT_BASE", lerobot_base)
    monkeypatch.setattr(
        auto_converter,
        "convert_single_recording",
        lambda **kwargs: 100,
    )

    call_order: list[str] = []

    class _OrderedCreator(_FakeCreator):
        def finalize(self) -> None:
            call_order.append("finalize_called")

        def correct_video_timestamps(self) -> None:
            call_order.append("correct_video_timestamps")

        def patch_episodes_metadata(self) -> None:
            call_order.append("patch_episodes_metadata")

    monkeypatch.setattr(auto_converter, "DataCreator", _OrderedCreator)

    state = ConvertState(lerobot_base / "convert_state.json")
    caplog.set_level(logging.INFO, logger="auto_converter")

    auto_converter.convert_task(
        "cell001", "pick_task", ["20260421_120000"], state,
    )

    finalizing_msgs = [
        r for r in caplog.records
        if "Finalizing:" in r.getMessage()
    ]
    finalized_msgs = [
        r for r in caplog.records
        if "Finalized:" in r.getMessage()
    ]

    assert len(finalizing_msgs) == 1, "Expected exactly one Finalizing: log"
    assert len(finalized_msgs) == 1, "Expected exactly one Finalized: log"
    assert finalizing_msgs[0].getMessage().strip() == "Finalizing: cell001/pick_task"
    assert finalized_msgs[0].getMessage().strip() == "Finalized: cell001/pick_task"

    # Order: Finalizing log -> finalize() called -> Finalized log
    finalizing_time = finalizing_msgs[0].created
    finalized_time = finalized_msgs[0].created
    assert finalizing_time < finalized_time
    assert call_order == [
        "finalize_called",
        "correct_video_timestamps",
        "patch_episodes_metadata",
    ]
```

**주의:** `_FakeCreator`와 `_write_raw_recording`, `ConvertState` import가 상단에 이미 있는 것 확인 (Line 28~56). `convert_single_recording` 심볼이 `auto_converter` 모듈에 직접 import 되어 있는지 확인. 없으면 `monkeypatch.setattr` 대상 경로를 `"auto_converter.convert_single_recording"` 대신 실제 경로로 조정.

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd rosbag2lerobot-svt && pytest test/test_auto_converter.py::test_convert_task_logs_finalizing_before_finalize -v
```

Expected: FAIL — `"Expected exactly one Finalizing: log"`. 현재 코드에는 `Finalizing:` 로그가 없음.

- [ ] **Step 3: auto_converter.py에 로그 1줄 추가**

`rosbag2lerobot-svt/auto_converter.py` 의 `convert_task()` 함수, 현재 `L262-277` 블록을 수정:

Before (`:263-270`):
```python
    # 9. Finalize dataset (per task)
    if creator is not None and creator.dataset is not None:
        try:
            creator.finalize()
            creator.correct_video_timestamps()
            creator.patch_episodes_metadata()
            if last_successful_serial is not None:
                _sync_persisted_count(state, cell_task, creator, last_successful_serial)
            logger.info("  Finalized: %s", cell_task)
```

After:
```python
    # 9. Finalize dataset (per task)
    if creator is not None and creator.dataset is not None:
        try:
            logger.info("  Finalizing: %s", cell_task)
            creator.finalize()
            creator.correct_video_timestamps()
            creator.patch_episodes_metadata()
            if last_successful_serial is not None:
                _sync_persisted_count(state, cell_task, creator, last_successful_serial)
            logger.info("  Finalized: %s", cell_task)
```

변경은 `try:` 바로 다음에 `logger.info("  Finalizing: %s", cell_task)` 한 줄 추가. 포맷은 기존 `Finalized:` 와 대칭 (2 leading spaces 유지).

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd rosbag2lerobot-svt && pytest test/test_auto_converter.py -v
```

Expected: 신규 테스트 PASS. 기존 테스트 회귀 없음.

- [ ] **Step 5: Commit**

```bash
git add rosbag2lerobot-svt/auto_converter.py rosbag2lerobot-svt/test/test_auto_converter.py
git commit -m "feat(converter): emit Finalizing log before per-task finalize block"
```

---

## Task 3: LogEventType 타입 확장

**Files:**
- Modify: `frontend/src/types/index.ts:130`

- [ ] **Step 1: 타입 확장**

`frontend/src/types/index.ts` 130번 줄 수정:

Before:
```ts
export type LogEventType = 'converted' | 'failed' | 'converting' | 'scan' | 'warning' | 'info' | 'error'
```

After:
```ts
export type LogEventType =
  | 'converted'
  | 'failed'
  | 'converting'
  | 'finalizing'
  | 'finalized'
  | 'scan'
  | 'warning'
  | 'info'
  | 'error'
```

`LogEvent` interface (L132-145)의 `task?: string`, `ts: string` 필드는 이미 있으므로 추가 필드 불필요.

- [ ] **Step 2: 타입 체크**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 에러 없음. (아직 사용하는 곳이 없으므로 unused 경고도 안 남)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(converter): add finalizing/finalized to LogEventType"
```

---

## Task 4: ConverterPage로 WebSocket 구독 끌어올리기

**Files:**
- Modify: `frontend/src/components/ConverterPage.tsx`
- Modify: `frontend/src/components/ConverterLogs.tsx`

이 task는 리팩터링 성격이 강함 — 동작은 그대로 유지하면서 WS 소유권만 이전. 기능 확장은 Task 5/6에서.

- [ ] **Step 1: ConverterPage에 WS 구독 로직 이식**

`frontend/src/components/ConverterPage.tsx` 를 전체 교체:

```tsx
import { useEffect, useRef, useState } from 'react'
import { ConverterControls } from './ConverterControls'
import { ConverterProgress } from './ConverterProgress'
import { ConverterLogs } from './ConverterLogs'
import type { ConverterStatus, LogEvent } from '../types'

interface Props {
  status: ConverterStatus
  onRefresh: () => void
}

const MAX_EVENTS = 200

export function ConverterPage({ status, onRefresh }: Props) {
  const [logsOpen, setLogsOpen] = useState(false)
  const [events, setEvents] = useState<LogEvent[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  // 10s polling while running — unchanged behavior
  useEffect(() => {
    if (status.container_state !== 'running') return
    const id = setInterval(onRefresh, 10000)
    return () => clearInterval(id)
  }, [status.container_state, onRefresh])

  // WebSocket ownership moved up from ConverterLogs
  useEffect(() => {
    if (status.container_state !== 'running') {
      setEvents([])
      return
    }

    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0
    let cancelled = false

    const connect = () => {
      if (cancelled) return
      setEvents([])
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${proto}//${window.location.host}/api/converter/logs`)
      wsRef.current = ws

      ws.onmessage = (evt) => {
        try {
          const event: LogEvent = JSON.parse(evt.data)
          setEvents(prev => {
            const next = [...prev, event]
            return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next
          })
        } catch {
          // skip
        }
      }

      ws.onopen = () => { attempt = 0 }
      ws.onerror = () => {}
      ws.onclose = () => {
        if (cancelled) return
        attempt++
        const delay = Math.min(1000 * 2 ** attempt, 10000)
        reconnectTimer = setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
      wsRef.current = null
    }
  }, [status.container_state])

  return (
    <div className="converter-page">
      <ConverterControls
        containerState={status.container_state}
        dockerAvailable={status.docker_available}
        onRefresh={onRefresh}
      />
      <div className="converter-body">
        <ConverterProgress
          tasks={status.tasks}
          containerState={status.container_state}
          dockerAvailable={status.docker_available}
          events={events}
          onRefresh={onRefresh}
        />
      </div>
      <ConverterLogs
        containerState={status.container_state}
        events={events}
        open={logsOpen}
        onToggle={() => setLogsOpen(v => !v)}
      />
    </div>
  )
}
```

**동작 대칭성:**
- `setEvents([])` on reconnect attempt 및 on container !== running — 기존 `ConverterLogs` 로직과 동일.
- `MAX_EVENTS = 200` 크롭도 동일.
- exponential backoff 재연결 로직 동일.

- [ ] **Step 2: ConverterLogs에서 WS 로직 제거, events prop 수용**

`frontend/src/components/ConverterLogs.tsx` 수정. 함수 시그니처와 상단 hooks를 바꾼다.

Before (L1-8 + L137-186):
```tsx
import { useEffect, useRef, useState } from 'react'
import type { ConverterState, LogEvent } from '../types'

interface Props {
  containerState: ConverterState
  open: boolean
  onToggle: () => void
}
```

After:
```tsx
import { useEffect, useRef, useState } from 'react'
import type { ConverterState, LogEvent } from '../types'

interface Props {
  containerState: ConverterState
  events: LogEvent[]
  open: boolean
  onToggle: () => void
}
```

함수 본문에서 `L137-186` 의 내부 `events` 상태와 WS useEffect를 제거하고, prop으로 받은 `events`를 그대로 사용:

Before:
```tsx
export function ConverterLogs({ containerState, open, onToggle }: Props) {
  const [events, setEvents] = useState<LogEvent[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (containerState !== 'running') return
    // ... 전체 WS 구독 블록 ...
  }, [containerState])
```

After:
```tsx
export function ConverterLogs({ containerState, events, open, onToggle }: Props) {
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
```

`useEffect` WS 블록을 **통째로 삭제**. `MAX_EVENTS` 상수도 이 파일에서는 더이상 쓰지 않으므로 제거. `formatTime`, `formatDuration`, `recordingName`, `recordingTask`, `eventTeaser`, `EventRow`, `counts`, `lastEvent` 계산, 자동 스크롤 useEffect, `handleScroll`, render 부분은 모두 그대로 유지.

- [ ] **Step 3: ConverterProgress 시그니처에 events prop 추가 (비어있는 통로)**

Task 4에서는 아직 사용하지 않지만, 컴파일이 통과하려면 `events` prop을 받을 수 있어야 한다. `frontend/src/components/ConverterProgress.tsx` Props 인터페이스에 추가만:

Before (L16-21):
```tsx
interface Props {
  tasks: ConverterTaskProgress[]
  containerState: ConverterState
  dockerAvailable: boolean
  onRefresh: () => void
}
```

After:
```tsx
interface Props {
  tasks: ConverterTaskProgress[]
  containerState: ConverterState
  dockerAvailable: boolean
  events: LogEvent[]
  onRefresh: () => void
}
```

**그리고 함수 파라미터 destructuring에 `events`를 추가하되 사용은 안 함 (Task 5에서 사용):**

```tsx
export function ConverterProgress({
  tasks,
  containerState,
  dockerAvailable,
  events: _events,
  onRefresh,
}: Props) {
```

`import` 에 `LogEvent` 추가:

```tsx
import type { ConverterState, ConverterTaskProgress, LogEvent } from '../types'
```

- [ ] **Step 4: 타입 체크 + 브라우저에서 WS 동작 확인**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 에러 없음.

컨테이너가 `running`일 때 개발 서버에서 Activity 패널을 열어 로그가 기존과 동일하게 스트림되는지 확인:

```bash
# 원 터미널에서
cd frontend && npm run dev
```

- 브라우저에서 Converter 페이지 이동
- Activity 토글 열기
- 컨테이너 start 후 `converting` / `converted` 로그 이벤트가 표시되는지 확인
- 탭을 닫고 다시 열어도 재연결이 정상 동작하는지 확인

동작이 기존과 동일하면 OK (Task 4는 순수 리팩터링이라 UI 변화 없음).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConverterPage.tsx frontend/src/components/ConverterLogs.tsx frontend/src/components/ConverterProgress.tsx
git commit -m "refactor(converter): lift WebSocket ownership to ConverterPage"
```

---

## Task 5: ConverterLogs에 finalizing/finalized 표시

**Files:**
- Modify: `frontend/src/components/ConverterLogs.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: EventRow 에 두 케이스 추가**

`frontend/src/components/ConverterLogs.tsx` 의 `EventRow` switch 문에서 `case 'converting':` 분기 바로 아래에 두 케이스 추가:

```tsx
case 'finalizing':
  return (
    <div className="log-event log-finalizing">
      {time}
      <span className="log-badge log-badge-finalizing">FIN</span>
      <span className="log-task">{event.task}</span>
    </div>
  )

case 'finalized':
  return (
    <div className="log-event log-finalized">
      {time}
      <span className="log-badge log-badge-ok">OK</span>
      <span className="log-task">{event.task}</span>
    </div>
  )
```

`eventTeaser` 함수에도 두 분기 추가:

```tsx
function eventTeaser(event: LogEvent): string {
  switch (event.type) {
    case 'converted':
      return `Converted ${recordingName(event.recording!)}`
    case 'failed':
      return `Failed ${recordingName(event.recording!)}${event.reason ? ` — ${event.reason}` : ''}`
    case 'converting':
      return `Processing ${event.task}`
    case 'finalizing':
      return `Finalizing ${event.task}`
    case 'finalized':
      return `Finalized ${event.task}`
    case 'scan':
      return `Scanned ${event.tasks} tasks, ${event.pending} pending`
    case 'warning':
      return event.message ?? 'Warning'
    case 'error':
      return event.message ?? 'Error'
    default:
      return event.message ?? ''
  }
}
```

- [ ] **Step 2: 로그 뱃지 스타일 추가**

`frontend/src/App.css` 에서 기존 `log-badge-*` 룰들이 있는 곳 근처에 추가. 기존 `log-badge-active`(Converting용)가 있는 선언을 찾고 그 아래에:

```css
.log-badge-finalizing {
  background: var(--c-blue-dim);
  color: var(--c-blue);
}
```

**찾는 법:** `grep -n "log-badge-active\|log-badge-scan\|log-badge-fail\|log-badge-ok" frontend/src/App.css` 로 기존 패턴 위치 확인 후 같은 영역에 배치.

- [ ] **Step 3: 타입 체크**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 에러 없음.

- [ ] **Step 4: 브라우저 수동 확인**

백엔드 Task 1/2가 머지된 상태에서 컨테이너 실행 후 Activity 패널에서 확인:
- `FIN` 파란 뱃지 라인이 나타나는지 (finalize 시작 시)
- 뒤이어 `OK` 라인이 나타나는지 (finalize 완료 시)
- 토글 닫힌 상태의 teaser 텍스트가 "Finalizing cell/task" / "Finalized cell/task" 로 바뀌는지

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConverterLogs.tsx frontend/src/App.css
git commit -m "feat(converter): render finalizing/finalized events in activity log"
```

---

## Task 6: ConverterProgress 카드에 상태 뱃지 + 애니메이션

**Files:**
- Modify: `frontend/src/components/ConverterProgress.tsx`
- Modify: `frontend/src/App.css:1268-1285`

이 task가 본 작업의 핵심.

- [ ] **Step 1: taskLive 유도 + 뱃지 렌더**

`frontend/src/components/ConverterProgress.tsx` 전체를 아래로 교체. 기존 validation 로직, startTask/runValidation, 전체 구조 유지. 변경은 (a) `taskLive` 유도, (b) 카드 footer 에 뱃지 삽입, (c) 카드 bar에 클래스 토글.

```tsx
import { useMemo, useState } from 'react'
import type { ConverterState, ConverterTaskProgress, LogEvent } from '../types'

type ValidationMode = 'quick' | 'full'
type TaskLive = 'converting' | 'finalizing' | 'done'

const API = '/api/converter'

const VALIDATION_STATUS_CLASS: Record<string, string> = {
  not_run: 'cvp-val-not-run',
  running: 'cvp-val-running',
  passed: 'cvp-val-passed',
  failed: 'cvp-val-failed',
  partial: 'cvp-val-partial',
}

interface Props {
  tasks: ConverterTaskProgress[]
  containerState: ConverterState
  dockerAvailable: boolean
  events: LogEvent[]
  onRefresh: () => void
}

function taskLabel(cell_task: string) {
  const parts = cell_task.split('/')
  return parts[parts.length - 1] || cell_task
}

function taskCell(cell_task: string) {
  const parts = cell_task.split('/')
  return parts[0] || ''
}

function deriveTaskLive(events: LogEvent[]): Map<string, TaskLive> {
  const live = new Map<string, TaskLive>()
  for (const ev of events) {
    if (!ev.task) continue
    if (ev.type === 'converting')       live.set(ev.task, 'converting')
    else if (ev.type === 'finalizing')  live.set(ev.task, 'finalizing')
    else if (ev.type === 'finalized')   live.set(ev.task, 'done')
  }
  return live
}

export function ConverterProgress({
  tasks,
  containerState,
  dockerAvailable,
  events,
  onRefresh,
}: Props) {
  const [starting, setStarting] = useState<string | null>(null)
  const [runningValidation, setRunningValidation] = useState<Set<string>>(new Set())

  const taskLive = useMemo(() => {
    if (containerState !== 'running') return new Map<string, TaskLive>()
    return deriveTaskLive(events)
  }, [containerState, events])

  const startTask = async (cell_task: string) => {
    setStarting(cell_task)
    try {
      const res = await fetch(`${API}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cell_task }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        console.error('start(task) failed:', body)
      }
      onRefresh()
    } finally {
      setStarting(null)
    }
  }

  const runValidation = async (cell_task: string, mode: ValidationMode) => {
    const key = `${cell_task}:${mode}`
    setRunningValidation(prev => {
      const next = new Set(prev)
      next.add(key)
      return next
    })
    try {
      const res = await fetch(`${API}/validate/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cell_task }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        console.error(`validate(${mode}) failed:`, body)
      }
      onRefresh()
    } finally {
      setRunningValidation(prev => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }
  }

  if (tasks.length === 0) {
    return <div className="cvp-empty">No conversion data</div>
  }

  const totals = tasks.reduce(
    (acc, t) => ({
      total: acc.total + t.total,
      done: acc.done + t.done,
      pending: acc.pending + t.pending,
      failed: acc.failed + t.failed,
    }),
    { total: 0, done: 0, pending: 0, failed: 0 },
  )

  const overallPct = totals.total > 0 ? Math.round((totals.done / totals.total) * 100) : 0
  const canStart = dockerAvailable
    && containerState !== 'running'
    && containerState !== 'building'
    && starting === null

  const canValidate = canStart

  return (
    <div className="cvp-root">
      <div className="cvp-hero">
        <div className="cvp-hero-left">
          <span className="cvp-pct">{overallPct}</span>
          <span className="cvp-pct-unit">%</span>
        </div>
        <div className="cvp-hero-right">
          <div className="cvp-bar-wide">
            <div className="cvp-bar-fill" style={{ width: `${overallPct}%` }} />
          </div>
          <div className="cvp-pills">
            <span className="cvp-pill cvp-pill-green">
              <span className="cvp-pill-num" style={{ fontFamily: 'var(--font-mono)' }}>{totals.done}</span>
              <span className="cvp-pill-label">done</span>
            </span>
            <span className="cvp-pill cvp-pill-yellow">
              <span className="cvp-pill-num" style={{ fontFamily: 'var(--font-mono)' }}>{totals.pending}</span>
              <span className="cvp-pill-label">pending</span>
            </span>
            {totals.failed > 0 && (
              <span className="cvp-pill cvp-pill-red">
                <span className="cvp-pill-num" style={{ fontFamily: 'var(--font-mono)' }}>{totals.failed}</span>
                <span className="cvp-pill-label">failed</span>
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="cvp-cards">
        {tasks.map(t => {
          const pct = t.total > 0 ? Math.round((t.done / t.total) * 100) : 0
          const hasPending = t.pending > 0
          const disabled = !canStart || !hasPending
          const validateDisabled = !canValidate
          const isStartingThis = starting === t.cell_task
          const quick = t.validation.quick
          const full = t.validation.full
          const isQuickRunning = runningValidation.has(`${t.cell_task}:quick`)
          const isFullRunning = runningValidation.has(`${t.cell_task}:full`)

          const live = taskLive.get(t.cell_task)
          const barClass = live === 'finalizing' ? 'cvp-card-bar is-finalizing' : 'cvp-card-bar'
          const fillClass = live === 'converting'
            ? 'cvp-card-bar-fill is-converting'
            : 'cvp-card-bar-fill'
          const fillWidth = live === 'finalizing' ? '100%' : `${pct}%`

          return (
            <div key={t.cell_task} className="cvp-card">
              <div className="cvp-card-header">
                <span className="cvp-card-cell">{taskCell(t.cell_task)}</span>
                <span className="cvp-card-name">{taskLabel(t.cell_task)}</span>
                <span className="cvp-card-fraction" style={{ fontFamily: 'var(--font-mono)' }}>
                  {t.done}/{t.total}
                </span>
              </div>
              <div className={barClass}>
                <div className={fillClass} style={{ width: fillWidth }} />
              </div>
              <div className="cvp-card-footer">
                <div className="cvp-card-footer-left">
                  {live === 'converting' && (
                    <span
                      className="cvp-status-badge st-converting"
                      role="status"
                      aria-live="polite"
                    >
                      <span className="dot" />Converting
                    </span>
                  )}
                  {live === 'finalizing' && (
                    <span
                      className="cvp-status-badge st-finalizing"
                      role="status"
                      aria-live="polite"
                    >
                      <span className="dot" />Finalizing
                    </span>
                  )}
                  {live === 'done' && (
                    <span className="cvp-status-badge st-done">
                      <span className="dot" />Done
                    </span>
                  )}
                  {!live && t.failed > 0 && (
                    <div className="cvp-card-failed">{t.failed} failed</div>
                  )}
                </div>
                <button
                  type="button"
                  className="btn-secondary cvp-card-convert"
                  disabled={disabled}
                  onClick={() => startTask(t.cell_task)}
                >
                  {isStartingThis ? 'Starting...' : 'Convert'}
                </button>
              </div>

              <div className="cvp-card-validation-row">
                <div className="cvp-card-validation">
                  <div className="cvp-card-val-meta">
                    <span className="cvp-card-val-title">Quick</span>
                    <span className={`cvp-card-val-badge ${VALIDATION_STATUS_CLASS[quick.status] ?? 'cvp-val-not-run'}`}>
                      {quick.status}
                    </span>
                  </div>
                  <div className="cvp-card-val-summary">{quick.summary}</div>
                  <button
                    type="button"
                    className="btn-secondary cvp-card-validate"
                    disabled={validateDisabled || isQuickRunning}
                    onClick={() => runValidation(t.cell_task, 'quick')}
                  >
                    {isQuickRunning ? 'Checking...' : 'Quick Check'}
                  </button>
                </div>

                <div className="cvp-card-validation">
                  <div className="cvp-card-val-meta">
                    <span className="cvp-card-val-title">Full</span>
                    <span className={`cvp-card-val-badge ${VALIDATION_STATUS_CLASS[full.status] ?? 'cvp-val-not-run'}`}>
                      {full.status}
                    </span>
                  </div>
                  <div className="cvp-card-val-summary">{full.summary}</div>
                  <button
                    type="button"
                    className="btn-secondary cvp-card-validate"
                    disabled={validateDisabled || isFullRunning}
                    onClick={() => runValidation(t.cell_task, 'full')}
                  >
                    {isFullRunning ? 'Checking...' : 'Full Check'}
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

**대칭 유지 포인트:**
- `deriveTaskLive`가 forward-only: `converting → finalizing → done` 순서대로 덮어써짐.
- `containerState !== 'running'`이면 빈 맵 → 모든 카드 Idle.
- 같은 task에 대해 더 최신 이벤트가 더 앞선 상태로 가는 경우(예: 재연결 후 replay로 `finalized` 다음에 `converting`이 옴 — 새 cycle 진입)도 `for...of` 순서대로 덮어써지므로 자연스럽게 새 상태로 전환.
- Footer 좌측에 `cvp-card-footer-left` div를 신설 — 기존 `cvp-card-failed` 단독 자리를 `live` 표시/failed 카운터의 **or** 구조로 바꿈. 카드가 live 상태면 failed 카운터는 잠시 숨기고 live 뱃지만 표시 (단 두 개를 동시 노출하면 혼잡).

- [ ] **Step 2: CSS 추가**

`frontend/src/App.css` 의 `.cvp-card-bar-fill` 블록(`L1275-1280`) **아래**에 다음을 추가:

```css
/* Status badge for task cards */
.cvp-card-footer-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.cvp-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 3px;
  letter-spacing: 0.02em;
}
.cvp-status-badge .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  display: inline-block;
}

.cvp-status-badge.st-converting {
  background: var(--c-green-dim);
  color: var(--c-green);
}
.cvp-status-badge.st-converting .dot {
  background: var(--c-green);
  animation: cvp-blink 1.1s ease-in-out infinite;
}

.cvp-status-badge.st-finalizing {
  background: var(--c-blue-dim);
  color: var(--c-blue);
}
.cvp-status-badge.st-finalizing .dot {
  background: var(--c-blue);
  animation: cvp-blink 1.1s ease-in-out infinite;
}

.cvp-status-badge.st-done {
  background: var(--c-green-dim);
  color: var(--c-green);
}
.cvp-status-badge.st-done .dot {
  background: var(--c-green);
}

/* Converting bar shimmer */
.cvp-card-bar-fill.is-converting {
  background: linear-gradient(
    90deg,
    var(--c-green) 0%,
    rgba(166, 227, 161, 0.4) 40%,
    var(--c-green) 80%
  );
  background-size: 200% 100%;
  animation: cvp-shimmer 1.6s linear infinite;
}

/* Finalizing bar pulse */
.cvp-card-bar.is-finalizing {
  animation: cvp-pulse 1.6s ease-in-out infinite;
}
.cvp-card-bar.is-finalizing .cvp-card-bar-fill {
  background: var(--c-blue);
}

@keyframes cvp-blink {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.35; }
}
@keyframes cvp-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
@keyframes cvp-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(137, 180, 250, 0.35); }
  50%      { box-shadow: 0 0 0 2px rgba(137, 180, 250, 0.15); }
}

@media (prefers-reduced-motion: reduce) {
  .cvp-card-bar-fill.is-converting,
  .cvp-card-bar.is-finalizing,
  .cvp-status-badge .dot {
    animation: none;
  }
}
```

- [ ] **Step 3: 타입 체크 + 빌드**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Expected: 에러 없음, 빌드 성공.

- [ ] **Step 4: 브라우저 수동 확인**

백엔드(Task 1+2) 머지된 상태에서:

```bash
cd frontend && npm run dev
```

브라우저에서 Converter 페이지 이동 후 컨테이너 start. 아래 모두 관찰 가능해야 함:

- [ ] 변환 시작 후 해당 task 카드에 녹색 `Converting` 뱃지 + shimmer 흐름
- [ ] 카드별 숫자 `done/total`은 기존과 동일하게 녹화 1개당 +1
- [ ] 마지막 녹화가 완료된 뒤 파란 `Finalizing` 뱃지 + 파란 바 100% pulse
- [ ] finalize 완료 시 녹색 `Done` 뱃지 정적 표시
- [ ] 컨테이너 stop 시 `Converting`/`Finalizing` 뱃지가 사라지고 카드가 Idle로 복귀
- [ ] 브라우저 DevTools Rendering 패널에서 `prefers-reduced-motion: reduce` 에뮬레이트 시 shimmer/pulse/blink 모두 정지, 뱃지/색은 유지
- [ ] Quick Check / Full Check 버튼의 validation 뱃지와 진행 상태 뱃지가 같은 카드에 동시에 나타나도 시각 충돌 없음 (validation 뱃지는 하단의 별도 영역이므로 footer와 겹치지 않음)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConverterProgress.tsx frontend/src/App.css
git commit -m "feat(converter): show live Converting/Finalizing/Done state on task cards"
```

---

## Task 7: End-to-end 수동 통합 점검

코드 변경 없음. 지금까지 6 task가 한 브랜치에 쌓인 상태에서 전체 흐름을 한 번 돌려보기.

- [ ] **Step 1: 백엔드 + 프론트 전체 테스트 green 확인**

```bash
pytest tests/test_converter_router.py tests/test_converter_service.py tests/test_converter_validation_router.py tests/test_converter_validation_service.py -v
cd rosbag2lerobot-svt && pytest test/test_auto_converter.py -v
cd ../frontend && npx tsc --noEmit && npm run build
```

Expected: 모두 PASS / 빌드 OK.

- [ ] **Step 2: 실서버 시나리오 검증**

한 개 cell/task에 대해 최소 3개 이상 pending 상태에서:

1. 컨테이너 build (처음 한 번)
2. 단일 task `Convert` 버튼 클릭
3. Activity 패널 열고 `converting` → `converted` x N → `finalizing` → `finalized` 순서로 이벤트 라인이 찍히는지 확인
4. 같은 타이밍에 카드 뱃지가 `Converting` → `Finalizing` → `Done`으로 전환되는지 확인
5. `Done` 상태에서 폴링 한 사이클 뒤 `done/total`이 맞게 보이는지 확인

- [ ] **Step 3: 크래시 시나리오**

변환이 오래 걸리는 task에서:

1. Convert 시작 → Converting 뱃지 확인
2. `docker kill convert-server`로 강제 종료
3. 컨테이너 state 변화 감지 (최대 10초) 후 Converting 뱃지 사라지고 Idle 복귀
4. 무한 Finalizing 혹은 stale 뱃지 남지 않음을 확인

- [ ] **Step 4: 문서 업데이트가 필요한가?**

`CLAUDE.md`, 아키텍처 문서(`docs/architecture/*.md`) 등에 이번 상태 표시가 언급될 필요 있는지 훑어보고, 필요하면 별도 작은 커밋으로 추가. 필요 없으면 skip.

- [ ] **Step 5: PR 준비 (선택)**

커밋 6개 (Task 1~6) + 이 통합 점검에서 만약 문서 추가가 있었다면 커밋 7. `main` 과 비교해서 diff 정리:

```bash
git log --oneline main..HEAD
git diff main --stat
```

---

## Self-review 체크리스트 (실행자는 무시 — 작성자 확인용)

이 절은 계획 작성자 본인이 통과 확인한 내용입니다. 실행자는 건너뛰어도 됩니다.

- Spec 섹션 1~9 모두 task로 커버됨:
  - §3 상태 머신 → Task 6 `deriveTaskLive` + 렌더 분기
  - §4.1 WS 이벤트 2종 신규 → Task 1 (파서), Task 2 (생성)
  - §4.2 폴링 역할 유지 → Task 4 (폴링 useEffect 그대로)
  - §4.3 재연결/replay → Task 4 (`setEvents([])` on reconnect)
  - §5.1 백엔드 변경 → Task 1, 2
  - §5.2 프론트 변경 → Task 3, 4, 5, 6
  - §6 접근성/모션 → Task 6 CSS 블록의 `prefers-reduced-motion` + `role="status"`/`aria-live`
  - §7 실패 모드 → Task 7 시나리오 점검
  - §8 테스트 → Task 1 (파서), Task 2 (로그 순서), Task 6 수동 체크리스트
- Placeholder 없음, "similar to" 없음, 모든 step에 실제 코드/명령 수록.
- Task 3(타입)과 Task 6(사용처)의 필드명 (`task`, `type`) 일관.
- Task 4와 Task 5가 같은 파일(`ConverterLogs.tsx`)을 건드리는데, Task 4에서는 WS 로직 제거 + props 스위치만, Task 5에서 `EventRow` 케이스 추가 — 순서 의존성 명시.
- 커밋 메시지 컨벤션은 저장소의 최근 로그(`feat(auto_grade):`, `chore(sweep):`, `test:`)와 일관.
