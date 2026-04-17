# Converter Validation — Design

**Date:** 2026-04-18
**Status:** Approved (design)

## Goal

Converter 화면에서 각 `cell/task`에 대해 기존 `rosbag-to-lerobot` 검증 로직을 재사용한 수동 검증을 실행하고, 마지막 검증 결과를 저장해 새로고침 후에도 `상태 + 한 줄 요약`으로 확인할 수 있게 한다.

## Background

현재 converter UI는 Docker 기반 `auto_converter`의 build/start/stop, 로그 스트리밍, task별 conversion progress만 보여준다. 변환 자체에는 입력 topic/Hz/quality 검사와 결과 dataset 검증에 해당하는 기존 로직이 이미 `rosbag-to-lerobot` 쪽에 흩어져 있지만, 운영자는 변환 후 "이 dataset이 실제로 쓸 만한가"를 converter 화면 안에서 바로 확인할 수 없다.

이번 범위는 episode curation UI를 converter에 복제하는 것이 아니다. 목표는 기존 변환 검증 로직을 runtime-friendly service로 감싸서 converter 카드 단위로 재사용하는 것이다.

## Decisions Captured From Brainstorm

| # | Decision |
|---|----------|
| Q1 | Converter는 기존 검증 로직을 직접 재사용하는 `curation-tools` 내부 어댑터 방식으로 구현한다. 테스트 스위트/외부 커맨드 호출을 앱 기능으로 직접 노출하지 않는다. |
| Q2 | 검증 모드는 `빠른 검증`과 `전체 검증` 두 가지를 모두 지원한다. |
| Q3 | 초기 릴리스에서는 자동 검증을 넣지 않는다. `Quick Check`, `Full Check` 모두 수동 버튼으로만 실행한다. |
| Q4 | 검증 결과는 task별 마지막 결과를 저장해서 새로고침/재접속 후에도 유지한다. |
| Q5 | 카드 UI는 상세 리포트 대신 `미검증/통과/실패/부분통과/실행중` 상태와 한 줄 요약만 보여준다. |

## Architecture

### Runtime Validation Layer

`backend/converter/validation_service.py`를 새로 추가한다. 이 서비스는 sibling repo `rosbag-to-lerobot`의 기존 검증 코드를 직접 import해서 converter용 런타임 API로 감싼다.

- 검증 단위: `cell/task`
- 입력: `cell_task`, 검증 모드 (`quick` or `full`)
- 출력: 구조화된 검증 결과 (`status`, `summary`, `checked_at`)

서비스는 두 경로를 해석한다.

- raw 입력 경로: `/data/raw/<cell>/<task>`에 대응하는 호스트 경로
- lerobot 출력 경로: `/data/lerobot/<cell>/<task>`에 대응하는 호스트 경로

### Existing Logic Reuse

재사용 우선순위는 다음과 같다.

1. **빠른 검증**
   - `rosbag-to-lerobot`의 native validation/integrity 로직을 직접 함수 단위로 호출한다.
   - 목적은 "지금 이 dataset이 기본 구조와 수치 일관성을 만족하는가"를 빠르게 판정하는 것이다.
2. **전체 검증**
   - 빠른 검증을 전부 포함한다.
   - 추가로 더 무거운 dataset-level cross-check와 optional official loader smoke test를 수행한다.

테스트 코드 그 자체를 앱에서 직접 돌리지는 않는다. 대신 테스트가 검증하던 규칙을 런타임 서비스 코드로 옮기거나, 이미 import 가능한 검증 함수를 재사용한다.

### State Persistence

검증 결과는 기존 conversion progress와 같은 NAS 루트에 JSON 파일로 저장한다.

- 경로: `/mnt/synology/data/data_div/2026_1/lerobot/convert_validation_state.json`
- 저장 범위: task별 마지막 `quick` 결과, 마지막 `full` 결과만 저장
- 목적: 새로고침/재접속 후에도 마지막 상태와 요약을 즉시 복원

별도 DB 마이그레이션은 하지 않는다. converter 기능은 기존처럼 NAS 상태 파일 기반으로 유지한다.

## Validation Behavior

### Status Model

검증 상태는 다섯 가지로 통일한다.

- `not_run`
- `running`
- `passed`
- `failed`
- `partial`

`partial`은 전체 검증에서 optional 단계가 건너뛰어진 경우를 위해 둔다. 대표적으로 official `lerobot` loader가 현재 환경에 없을 때 전체 검증은 실패 대신 `partial`로 기록한다.

### Quick Validation

빠른 검증은 운영용 기본 체크다. 목적은 "변환 결과를 지금 바로 사용할 수 있는지"를 짧고 예측 가능하게 판단하는 것이다.

검사 항목:

- output dataset 디렉터리 존재
- `meta/info.json` 존재
- `meta/tasks.parquet` 존재
- `meta/episodes/*.parquet` 최소 1개 존재
- `data/*.parquet` 최소 1개 존재
- 영상 dataset이면 `videos/**/*.mp4` 최소 1개 존재
- `info.json` 필수 키 검증
  - `total_episodes`
  - `total_frames`
  - `fps`
  - `features`
- data parquet 필수 컬럼 검증
  - `episode_index`
  - `frame_index`
  - `index`
  - `task_index`
  - `timestamp`
- episode/data parquet 기본 개수 일관성 검증
- 가능하면 변환 입력 단계에서 이미 계산 가능한 `Hz pass/fail`, `quality warning count`를 함께 요약에 반영

예시 요약:

- `Quick passed: 12 episodes, 0 warnings`
- `Quick failed: missing meta/tasks.parquet`
- `Quick failed: info.total_frames mismatch`

### Full Validation

전체 검증은 수동 심화 점검이다.

- 빠른 검증을 반드시 먼저 수행한다.
- 빠른 검증이 실패하면 전체 검증도 즉시 `failed`로 종료한다.

추가 검사 항목:

- `info.json` 수치와 실제 parquet row 수 교차 검증
- episode metadata와 data parquet의 episode/task 참조 일치 검증
- task index 참조 일치 검증
- video file 존재/기본 접근성 재검증
- 환경에 `lerobot`가 설치된 경우 official loader smoke test 수행

official loader 규칙:

- loader 성공: `passed`
- loader 실패: `failed`
- `lerobot` 미설치 또는 요구 버전 미만: 전체 검증은 `partial`, summary는 `official loader skipped`

예시 요약:

- `Full passed: dataset OK, loader OK`
- `Full partial: dataset OK, official loader skipped`
- `Full failed: episode parquet/task index mismatch`

### Execution Policy

- 자동 검증은 이번 범위에서 지원하지 않는다.
- `Quick Check`, `Full Check`는 모두 사용자가 task 카드에서 수동으로 실행한다.
- 같은 task/mode에 대해 이미 검증이 실행 중이면 중복 요청은 막는다.

## Backend

### New Service: `backend/converter/validation_service.py`

책임:

- `cell_task`를 raw/output 경로로 해석
- sibling repo import 경로 설정
- quick/full validation 수행
- 결과 JSON 파일 읽기/쓰기
- running 상태 동시성 제어

제안 함수 형태:

- `run_quick_validation(cell_task: str) -> ValidationResult`
- `run_full_validation(cell_task: str) -> ValidationResult`
- `read_validation_state() -> dict[str, TaskValidationState]`
- `write_validation_state(state: dict[str, TaskValidationState]) -> None`

서비스는 converter의 기존 Docker state 파일과 같은 방식으로 단순 JSON 원자적 쓰기(`tmp` 후 replace)로 저장한다.

### Router Changes: `backend/converter/router.py`

새 endpoint:

- `POST /api/converter/validate/quick`
- `POST /api/converter/validate/full`
- `GET /api/converter/validation`

요청 body:

```json
{ "cell_task": "cell001/task_a" }
```

응답 규칙:

- 성공: 마지막 결과 반환
- 동일 task/mode 중복 실행: `409`
- output dataset 없음 등 검증 전제조건 미충족: `400`
- 예기치 않은 내부 오류: `500`

기존 `GET /api/converter/status` 응답의 각 task 항목에 `validation` 필드를 합쳐 내려준다. 프론트가 별도 join 로직 없이 status만 읽으면 되게 한다.

### Data Contract

저장 파일 구조:

```json
{
  "cell001/task_a": {
    "quick": {
      "status": "passed",
      "summary": "Quick passed: 12 episodes, 0 warnings",
      "checked_at": "2026-04-18T10:15:00+09:00"
    },
    "full": {
      "status": "partial",
      "summary": "Full partial: dataset OK, official loader skipped",
      "checked_at": "2026-04-18T10:17:00+09:00"
    }
  }
}
```

status payload 예시:

```json
{
  "cell_task": "cell001/task_a",
  "total": 12,
  "done": 12,
  "pending": 0,
  "failed": 0,
  "retry": 0,
  "validation": {
    "quick": {
      "status": "passed",
      "summary": "Quick passed: 12 episodes, 0 warnings"
    },
    "full": {
      "status": "partial",
      "summary": "Full partial: dataset OK, official loader skipped"
    }
  }
}
```

## Frontend

### Types

`frontend/src/types/index.ts`에 converter validation 타입을 추가한다.

- `ConverterValidationStatus`
- `ConverterValidationResult`
- `ConverterTaskProgress.validation`

### `ConverterProgress.tsx`

각 task 카드에 다음 요소를 추가한다.

- `Quick Check` 버튼
- `Full Check` 버튼
- quick 상태 배지
- full 상태 배지
- 최근 결과 한 줄 요약

요약 우선순위:

1. full summary가 있으면 full summary
2. 없으면 quick summary
3. 둘 다 없으면 `Not validated`

버튼 정책:

- `Quick Check`
  - output dataset이 없으면 비활성
  - 해당 quick 검증이 실행 중이면 비활성
- `Full Check`
  - `pending > 0`이면 비활성
  - output dataset이 없으면 비활성
  - 해당 full 검증이 실행 중이면 비활성

이번 범위에서 상세 펼침 UI는 넣지 않는다. 실패 사유는 요약 한 줄 안에만 포함한다.

## Error Handling

- sibling repo import 실패: API는 `500`, summary는 저장하지 않는다.
- 검증 중 예외 발생: 해당 mode 결과를 `failed`로 저장하고 요약에 핵심 오류를 남긴다.
- 상태 파일 손상/파싱 실패: 빈 상태로 fallback하고 warning log를 남긴다.
- 공식 loader 미설치: full validation은 `partial`, 에러가 아니라 예상 가능한 degrade로 처리한다.

## Testing

Backend:

- validation state file read/write round-trip
- quick validation
  - dataset dir missing → failed
  - required files missing → failed
  - minimal valid dataset fixture → passed
- full validation
  - quick 실패 전파 → failed
  - loader 미설치 → partial
  - 교차 검증 mismatch → failed
- router
  - `POST /validate/quick` success
  - `POST /validate/full` success
  - same task/mode concurrent request → 409
  - `/status` payload includes validation block

Frontend:

- task card renders quick/full validation badges
- summary priority prefers full over quick
- quick/full button click sends the correct API request
- disable states
  - full disabled while `pending > 0`
  - mode-specific running disables only that button

## Out of Scope

- 자동 검증
- 상세 검증 리포트/아코디언 UI
- dataset page와 converter validation 결과를 공유하는 통합 검수 화면
- validation history/audit trail
- converter Docker 컨테이너 내부에서 검증을 직접 수행하도록 구조 변경
