# Converter 페이지 진행 상태 표시 설계

- **일자**: 2026-04-21
- **범위**: Converter 페이지 각 task 카드가 "변환 진행중"과 "finalize 진행중" 상태를 명확히 표시하도록 개선
- **참여 파일**: `rosbag2lerobot-svt/auto_converter.py`, `backend/converter/router.py`, `frontend/src/types/index.ts`, `frontend/src/components/ConverterPage.tsx`, `frontend/src/components/ConverterLogs.tsx`, `frontend/src/components/ConverterProgress.tsx`, `frontend/src/App.css`

## 1. 배경 / 문제

현재 Convert 페이지(`ConverterProgress.tsx`)는 task별 카드에 `done/total` 숫자와 누적 % 바만 표시한다. 실제 사용 관점에서 두 가지가 명확하지 않다.

1. **"지금 이 task가 살아서 돌고 있다"는 피드백 부재** — `done/total`은 녹화 하나가 끝날 때마다만 갱신되므로 하나의 녹화 변환이 오래 걸리는 구간(30초 ~ 수분) 동안 카드가 멈춰 보인다. 실제로는 진행 중이지만 UI만 보면 알 수 없다.
2. **finalize 단계가 UI에 등장하지 않음** — `convert_task()`는 마지막 녹화가 끝난 뒤 `creator.finalize()` + `correct_video_timestamps()` + `patch_episodes_metadata()`를 순차 실행한다. 이 구간은 task 크기에 따라 수 초에서 수 분 이상 걸리지만 프론트에는 어떤 신호도 오지 않는다. `auto_converter`는 완료 후 `Finalized: cell/task` 로그만 찍으므로 "finalize **중**"을 알 방법이 없다.

## 2. 목표 / 비목표

### 목표

- 각 task 카드에서 **Converting / Finalizing / Done**을 시각적으로 구분.
- Converting 동안에도 카드가 "살아 있다"는 것이 애니메이션으로 보이게 함.
- finalize 진행 중에도 카드가 명시적으로 "Finalizing" 상태를 표현.
- 기존 숫자(`done/total`)와 % 바의 진실의 원천은 유지. 뱃지/애니메이션은 **표시 상태 전환 타이밍**만 담당.

### 비목표

- 진행률 추정(ETA) 표시.
- finalize 내부 서브스테이지(flush / video ts / meta patch) 각각의 표시 — 로그 라인이 없어서 거짓 신호 위험.
- 상단 hero 영역의 전역 "현재 처리중" 배너 — 카드 단위 표시만으로 충분하다고 판단.
- `cell_task`별 개별 WebSocket 채널.
- 프론트 단위 테스트 인프라 구축.

## 3. 카드 상태 머신

각 task 카드는 아래 네 상태 중 하나를 가진다.

| 상태 | 진입 조건 | 뱃지 | 바 |
|------|-----------|------|----|
| **Idle** | 컨테이너가 멈춰 있음, 또는 이 task에 활동 신호가 아직 없음 | 없음 | 정적 녹색 (`done/total`에 비례) |
| **Converting** | 이 task의 `converting` 이벤트 수신 후, `finalizing`/`finalized` 아직 없음 | `Converting` 녹색 깜빡 | 녹색 shimmer (좌→우 흐름) |
| **Finalizing** | 이 task의 `finalizing` 이벤트 수신 후, `finalized` 아직 없음 | `Finalizing` 파란 깜빡 | 파란색 pulse (100% 폭) |
| **Done** | 이 task의 `finalized` 이벤트 수신, 또는 폴링이 `done == total` 확인 | `Done` 녹색 정적 | 정적 녹색 100% |

### 일관성 규칙

- 전환은 `Idle → Converting → Finalizing → Done` 단방향. 백트래킹 없음.
- 컨테이너 상태가 `running`이 아니거나 WS가 끊기면 `Converting`/`Finalizing` 카드는 즉시 **Idle**로 복귀하되, 마지막 관측 숫자(`done/total`)는 유지.
- 두 개 이상 task가 동시에 `Converting`일 수 없음 (auto_converter가 직렬 처리). 혹시 이벤트가 중첩되면 마지막 `converting` 이벤트의 task만 Converting으로 간주, 나머지는 Idle.
- `Done`은 휘발적 표시이다. 새 scan cycle에서 해당 task에 pending이 다시 생기면 Idle로 돌아간다. 정적 `done == total` 자체는 기존 % 바로도 표현되므로 뱃지 없이도 상태 유추 가능.

## 4. 신호 소스

### 4.1 주 신호: WebSocket 실시간 이벤트

`/api/converter/logs`에서 스트리밍되는 파싱 로그 이벤트가 상태 전환의 1차 소스.

**새로 추가되는 이벤트 타입 두 개:**

| type | 발생 시점 | 추출 필드 |
|------|-----------|-----------|
| `finalizing` | 컨테이너가 `  Finalizing: cell/task` 로그를 찍은 직후 | `task: "cell/task"` |
| `finalized`  | 컨테이너가 `  Finalized: cell/task` 로그를 찍은 직후  | `task: "cell/task"` |

기존 이벤트 타입(`scan`, `converting`, `converted`, `failed`, `warning`, `info`, `error`)은 그대로.

### 4.2 보조 신호: `/api/converter/status` 폴링

`ConverterPage`는 컨테이너가 `running`일 때 10초마다 `/status`를 폴링한다. 이 값은 `done/total` 숫자의 **진실의 원천**이다.

불일치 시 우선순위:
- 숫자(`done/total`, `failed`, `pending`) → 폴링 응답
- 뱃지/애니메이션(Converting/Finalizing/Done) → WS 이벤트

### 4.3 초기 연결과 replay

- `ConverterLogs`는 WS 연결 시점에 `setEvents([])`로 리셋한다. 이 동작은 유지. 재연결 시 오래된 이벤트가 남아 잘못된 상태로 남는 것을 방지.
- `docker logs -f --tail 200`이 기본이므로 재연결 시 최근 200줄이 replay된다. 상태 머신이 forward-only이므로 이미 `finalized`된 task에 대해 `finalizing`이 다시 와도 시각 상태에는 영향 없음 (이미 Done 또는 Idle).

## 5. 구성 요소 역할 분담

### 5.1 백엔드

**`rosbag2lerobot-svt/auto_converter.py`**

`convert_task()` 내부, `creator.finalize()` 호출 **직전**에 한 줄 추가.

```python
# 9. Finalize dataset (per task)
if creator is not None and creator.dataset is not None:
    try:
        logger.info("  Finalizing: %s", cell_task)   # ← 추가
        creator.finalize()
        creator.correct_video_timestamps()
        creator.patch_episodes_metadata()
        ...
        logger.info("  Finalized: %s", cell_task)    # ← 기존
```

기존 `Finalized:` 라인의 포맷/위치/의미는 바꾸지 않는다.

**`backend/converter/router.py`**

`_parse_log_line()`에 두 정규식과 분기를 추가한다.

```python
_FINALIZING_RE = re.compile(r"Finalizing:\s+(.+)$")
_FINALIZED_RE  = re.compile(r"Finalized:\s+(.+)$")
```

`_TS_RE` 매칭 이후, 기존 `_CONVERTING_RE` 분기와 대칭되는 위치에 두 분기를 추가한다. 매칭 시 `{"type": "finalizing"|"finalized", "ts": ts, "task": task}` 형태의 dict를 반환. 기존 generic info로 떨어지던 `Finalized:` 라인은 이제 `finalized` 타입으로 분리된다.

### 5.2 프론트엔드

**`frontend/src/types/index.ts`**

`LogEventType`에 두 리터럴 추가.

```ts
export type LogEventType =
  | 'converted' | 'failed' | 'converting'
  | 'finalizing' | 'finalized'
  | 'scan' | 'warning' | 'info' | 'error'
```

`LogEvent.task` 필드는 이미 존재하므로 재사용.

**`frontend/src/components/ConverterPage.tsx` — WS 구독 끌어올리기**

현재는 `ConverterLogs`가 자체적으로 WS를 구독한다. 이번 작업에서 **WS 구독 로직을 `ConverterPage`로 상향**하고, 받은 `events`를 `ConverterProgress`와 `ConverterLogs` 양쪽에 prop으로 내려준다.

- 재연결/backoff 로직, `MAX_EVENTS` 크롭 동작은 기존과 동일하게 `ConverterPage`에 옮겨 적재.
- 컨테이너 상태가 `running`일 때만 연결, 아닐 때는 이벤트 버퍼를 비움.
- 기존 10초 폴링도 그대로 유지.

**`frontend/src/components/ConverterLogs.tsx`**

- 자체 WS 로직을 제거하고 `events: LogEvent[]`를 prop으로 받음.
- `EventRow`에 `finalizing` / `finalized` 케이스 추가. 두 케이스는 `converting`과 유사한 단일 라인 (타임, 뱃지 `FIN` / `OK`, task 이름). 여기서 UI 텍스트는 기존 UX 톤(간결) 유지.

**`frontend/src/components/ConverterProgress.tsx`**

`events: LogEvent[]`를 prop으로 받고 task별로 `liveStatus` 맵을 유도한다.

```ts
// pseudo
const taskLive = new Map<string, 'converting' | 'finalizing' | 'done'>()
for (const ev of events) {
  if (ev.type === 'converting'  && ev.task) taskLive.set(ev.task, 'converting')
  if (ev.type === 'finalizing'  && ev.task) taskLive.set(ev.task, 'finalizing')
  if (ev.type === 'finalized'   && ev.task) taskLive.set(ev.task, 'done')
}
// 컨테이너가 running이 아니면 전체 맵 폐기 → 모두 Idle
```

각 카드 렌더에서 `containerState === 'running'`일 때만 `taskLive.get(cell_task)`을 보고 뱃지/애니메이션 클래스를 결정한다.

**`frontend/src/App.css`**

- `.cvp-status-badge`, `.cvp-status-badge .dot` 기본 스타일.
- `.st-converting`, `.st-finalizing`, `.st-done` 변형 (색상: `--c-green`, `--c-blue`).
- `.cvp-card-bar-fill.is-converting` — `@keyframes cvp-shimmer` 적용.
- `.cvp-card-bar.is-finalizing` — `@keyframes cvp-pulse` 적용 + 내부 fill 파란색 100%.
- `.cvp-status-badge .dot`에 `@keyframes cvp-blink` 적용 (Converting / Finalizing만).
- `@media (prefers-reduced-motion: reduce)` 블록에서 세 keyframes 모두 `animation: none`.

기존에 정의된 CSS 토큰(`--c-green`, `--c-green-dim`, `--c-blue`, `--c-blue-dim`, `--border2`, `--text`, `--text-muted`)만 사용한다. 새 토큰 추가 없음.

## 6. 접근성 / 모션

- `prefers-reduced-motion: reduce` 환경에서 shimmer, pulse, dot blink 모두 정지. 뱃지 색과 텍스트는 유지되므로 상태 인지에는 영향 없음.
- 뱃지 텍스트("Converting", "Finalizing", "Done")는 **항상 가시**. 색만으로 상태를 전달하지 않음 (색약 대응).
- 상태 뱃지 래퍼에 `role="status"` + `aria-live="polite"` 부여. 스크린 리더는 상태 전환을 차분히 읽음.

## 7. 실패 모드 / 엣지 케이스

1. **향후 로그 포맷이 바뀜** — 정규식이 매칭 실패. 카드는 Idle로 보이고 기능이 부분 열화(숫자만 폴링으로 갱신). 파서 테스트가 조기 감지.
2. **WS 연결 자체가 실패** — 모든 카드 Idle. 숫자는 폴링으로 갱신되며 hero의 전체 % 움직임으로 진행은 간접 파악 가능. 지금 동작과 동일.
3. **프로세스 크래시로 `finalized`가 안 옴** — 카드는 Finalizing pulse 유지. 10초 폴링이 컨테이너 state `exited`를 감지하는 즉시 Idle로 복귀. 무한 Finalizing 없음.
4. **새 scan cycle에서 같은 task에 pending이 다시 생김** — 새 `converting` 이벤트로 Converting에 재진입. forward-only 규칙의 의도된 예외.
5. **WS 재연결 후 로그 replay** — `--tail 200`로 최근 200줄 replay. 이미 Done/Idle인 카드의 `finalizing`/`finalized`가 재수신되어도 forward-only 상태 머신 + `containerState` 체크로 시각 영향 없음.
6. **단일 task 버튼을 사용자가 연타** — `ConverterProgress.startTask`는 이미 `starting` 락을 가짐. 이번 변경은 이 락 동작을 건드리지 않음.

## 8. 테스트

### 8.1 백엔드 (pytest)

**`tests/test_converter_parse_log_line.py`** (신규)
- `"2026-04-21 12:34:56 [INFO]   Finalizing: cell001/task_a"` → `{"type": "finalizing", "ts": "2026-04-21 12:34:56", "task": "cell001/task_a"}`
- `"2026-04-21 12:34:58 [INFO]   Finalized: cell001/task_a"` → `{"type": "finalized", ...}`
- 기존 `Converting: cell/task: N new recordings` 라인은 여전히 `converting` 타입으로 파싱됨 (회귀 방지).

**`rosbag2lerobot-svt/test/test_auto_converter.py`** (기존 파일 확장)
- `convert_task()` 실행 시 `creator.finalize()` 호출 **직전**에 `Finalizing: %s` 로그가 찍히는지 caplog으로 검증. 순서: Finalizing 로그 → finalize() 호출 → Finalized 로그.

### 8.2 프론트엔드 — 수동 검증 체크리스트

- [ ] 컨테이너 start 후 카드가 Idle → Converting → Finalizing → Done 순서로 전환.
- [ ] Converting 동안 바에 shimmer가 보임.
- [ ] finalize가 오래 걸리는 task(예: video ts 보정이 긴 cell/task)에서 pulse가 실제로 관찰됨.
- [ ] 컨테이너 재시작 후 WS 재연결 시 상태 정상 복구.
- [ ] 브라우저에서 `prefers-reduced-motion: reduce` 설정 시 애니메이션 정지, 뱃지/색은 유지.
- [ ] validation을 실행 중인 카드에서도 진행 상태 뱃지가 정상 표시, 시각 충돌 없음.
- [ ] 컨테이너 stop 시 Converting/Finalizing 카드가 즉시 Idle로 복귀.

## 9. 변경 요약

| 파일 | 종류 | 변경 |
|------|------|------|
| `rosbag2lerobot-svt/auto_converter.py` | 수정 | `creator.finalize()` 직전 `Finalizing: %s` 로그 1줄 |
| `backend/converter/router.py` | 수정 | `_FINALIZING_RE`, `_FINALIZED_RE` + 2개 분기 |
| `frontend/src/types/index.ts` | 수정 | `LogEventType`에 `'finalizing' \| 'finalized'` |
| `frontend/src/components/ConverterPage.tsx` | 수정 | WS 구독 상향, events를 자식에 전달 |
| `frontend/src/components/ConverterLogs.tsx` | 수정 | WS 로직 제거, events prop 사용, EventRow에 두 케이스 |
| `frontend/src/components/ConverterProgress.tsx` | 수정 | events로 taskLive 유도, 카드에 뱃지/애니메이션 렌더 |
| `frontend/src/App.css` | 수정 | 상태 뱃지·shimmer·pulse·reduced-motion CSS |
| `tests/test_converter_parse_log_line.py` | 신규 | 파서 단위 테스트 |
| `rosbag2lerobot-svt/test/test_auto_converter.py` | 수정 | Finalizing 로그 순서 검증 |

**신규 설정/토큰/의존성 없음.**
