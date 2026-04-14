# Converter Control Panel — Design Spec

curation-tools 웹 UI에서 rosbag-to-lerobot auto_converter Docker 컨테이너를 시작/정지하고, 실시간 로그 및 변환 현황을 확인하는 기능.

## Context

- `rosbag-to-lerobot/auto_converter.py` — NAS를 모니터링하며 MCAP → LeRobot 변환을 수행하는 무한 루프 서버
- 현재 `main.sh` interactive menu를 통해 Docker Compose로 실행/중지
- curation-tools 웹 UI에서 동일한 제어를 가능하게 함

## Architecture

```
[React UI]  ←WebSocket→  [FastAPI converter router]  →  docker compose CLI
   │                              │
   ├─ 시작/정지 버튼               ├─ POST /converter/build
   ├─ 실시간 로그 뷰어             ├─ POST /converter/start
   ├─ 변환 현황 테이블             ├─ POST /converter/stop
   └─ 상태 인디케이터(TopNav)       ├─ GET  /converter/status
                                  ├─ WS   /converter/logs
                                  └─ GET  /converter/progress
```

## Backend

### Service: `converter_service.py`

Docker CLI를 감싸는 서비스 레이어.

**Docker 명령 매핑:**

| 동작 | 실행 명령 |
|------|----------|
| Build | `docker compose -p convert-server -f {COMPOSE_FILE} build --no-cache convert-server` |
| Start | `docker compose -p convert-server -f {COMPOSE_FILE} run -d --name convert-server convert-server python3 /app/auto_converter.py` |
| Stop | `docker compose -p convert-server -f {COMPOSE_FILE} down` |
| Status | `docker inspect convert-server --format '{{.State.Status}}'` |
| Logs | `docker logs -f --tail 200 convert-server` |

**설정 (환경변수 오버라이드 가능):**

```python
ROSBAG_PROJECT = Path("/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot")
COMPOSE_FILE = ROSBAG_PROJECT / "docker" / "docker-compose.yml"
PROJECT_NAME = "convert-server"
CONTAINER_NAME = "convert-server"
```

**Progress 파싱:** auto_converter 로그의 scan table (`━━` 블록)을 `docker logs --tail 100`에서 마지막 블록을 찾아 정규식으로 파싱. Total 라인에서 요약 추출.

### Router: `converter.py`

| Endpoint | Method | 역할 |
|----------|--------|------|
| `/converter/status` | GET | 컨테이너 상태 + 마지막 scan 요약 |
| `/converter/build` | POST | Docker 이미지 빌드 (비동기, WebSocket으로 진행 전달) |
| `/converter/start` | POST | auto_converter 컨테이너 시작 |
| `/converter/stop` | POST | graceful shutdown (docker compose down) |
| `/converter/logs` | WebSocket | 실시간 로그 스트리밍 |
| `/converter/progress` | GET | task별 변환 현황 (total/done/pending/failed) |

### Error Handling

| 상황 | 처리 |
|------|------|
| Docker 데몬 미실행 | `docker_available: false` 반환, UI 안내 |
| 빌드 실패 | 빌드 로그를 WebSocket 전달, 상태 `error` 전환 |
| 이미 실행 중 + Start | 409 Conflict |
| 미실행 + Stop | 무시 (idempotent), 200 반환 |
| compose 파일 경로 오류 | 서버 시작 시 검증, 로그 경고 |

## Frontend

### TopNav 상태 인디케이터

로고 옆 원형 인디케이터. 초록(running), 회색(stopped), 노랑(building). 클릭 시 converter 페이지 이동.

### ConverterPage 레이아웃

```
┌──────────────────────────────────────────────┐
│  Control Bar                                 │
│  [Build] [Start] [Stop]    Status: ●Running  │
├──────────────────────────────────────────────┤
│  Progress Table                              │
│  Cell/Task    Total  Done  Pending  Failed   │
│  cell_a/t1      12     8       3       1     │
│  cell_a/t2       5     5       0       0     │
│  ─────────────────────────────────────────   │
│  Total           17    13       3       1    │
├──────────────────────────────────────────────┤
│  Log Viewer                                  │
│  2026-04-15 10:23:01 [INFO] Scan cycle 42   │
│  ...                          [auto-scroll ↓]│
└──────────────────────────────────────────────┘
```

### Components

| 컴포넌트 | 역할 |
|----------|------|
| `ConverterPage.tsx` | 페이지 레이아웃, 상태 관리 |
| `ConverterControls.tsx` | Build/Start/Stop 버튼 + 상태 뱃지 |
| `ConverterProgress.tsx` | task별 변환 현황 테이블 |
| `ConverterLogs.tsx` | WebSocket 로그 스트리밍 (auto-scroll, 최근 500줄) |

### Data Flow

- **상태 폴링**: `/converter/status` — 5초 간격, TopNav 인디케이터 + 버튼 활성/비활성 반영
- **Progress 폴링**: `/converter/progress` — 10초 간격 (running일 때만)
- **로그 스트리밍**: ConverterPage 진입 시 WebSocket 연결, 이탈 시 disconnect

### Button State

| 상태 | Build | Start | Stop |
|------|-------|-------|------|
| stopped | 활성 | 활성 | 비활성 |
| building | 비활성 | 비활성 | 활성 |
| running | 비활성 | 비활성 | 활성 |

## File Changes

**신규 파일:**
- `backend/routers/converter.py`
- `backend/services/converter_service.py`
- `frontend/src/components/ConverterPage.tsx`
- `frontend/src/components/ConverterControls.tsx`
- `frontend/src/components/ConverterProgress.tsx`
- `frontend/src/components/ConverterLogs.tsx`

**수정 파일:**
- `backend/main.py` — converter 라우터 등록
- `frontend/src/App.tsx` — converter view 추가
- `frontend/src/components/TopNav.tsx` — 상태 인디케이터 추가
- `frontend/src/types/index.ts` — converter 관련 타입 추가
- `frontend/src/hooks/useAppState.ts` — converter 네비게이션 추가
- `frontend/src/App.css` — converter 관련 스타일
