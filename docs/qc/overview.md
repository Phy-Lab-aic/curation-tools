# 에피소드 품질 평가(QC) 개요

LeRobot 데이터셋의 에피소드 품질을 자동 또는 반자동으로 평가하는 방법을 정리한 문서입니다.

---

## 등급 체계

curation-tools는 에피소드에 3단계 등급을 부여합니다.

| 등급 | 의미 |
|------|------|
| `Good` | 태스크 성공 + 궤적 품질 우수 |
| `Normal` | 태스크 성공 + 궤적 품질 보통 |
| `Bad` | 태스크 실패 또는 심각한 궤적 문제 |

등급은 에피소드 메타 parquet(`meta/episodes/`)의 `grade` 컬럼 또는 사이드카 JSON(`~/.local/share/curation-tools/annotations/`)에 저장됩니다. 사이드카가 parquet보다 우선합니다.

---

## 평가 방법 선택

```
scoring 데이터(tags.json)가 있는가?
    ├── YES → scoring 기반 자동 평가 (docs/qc/scoring-data.md)
    └── NO  → kinematic 신호 기반 평가 (docs/qc/kinematic-signals.md)
                    ↓
            영상/스칼라 시각화로 사람이 검수 (curation-tools UI)
```

---

## 데이터셋별 현황 (dfs/)

| 데이터셋 | 에피소드 수 | grade 컬럼 | scoring 연결 가능 | 권고 방법 |
|----------|------------|------------|------------------|-----------|
| `basic_aic_cheetcode_dataset` | 40 | 있음(비어있음) | 불가 (날짜 불일치) | 수동 큐레이션 |
| `changyong` | 90 | 없음 | 불가 (Serial_number 없음) | kinematic 자동 |
| `hojun` | 6 | 없음 | 불가 (Serial_number 없음) | 수동 큐레이션 |
| `hrchung` | 3 | 있음(비어있음) | 불가 (날짜 불일치) | 수동 큐레이션 |
| `jjhyeongg` | 43 | 없음 | 불가 (tags='unknown') | kinematic 자동 |

> `basic_aic_cheetcode_dataset`과 `hrchung`은 `Serial_number` 컬럼이 존재하지만,
> 날짜가 `~/aic_community_e2e/` 수집 배치와 다르므로 scoring 데이터를 연결할 수 없습니다.

---

## 새로 수집하는 데이터에 대한 권고

rosbag → LeRobot 변환 시점에 `tags.json`을 읽어 `grade`를 자동으로 채우는 것이 가장 효율적입니다.
변환 파이프라인(`rosbag-to-lerobot/src/main.py`)에는 이미 `grade` 필드가 준비되어 있습니다.

→ 구현 방법은 [scoring-data.md](scoring-data.md) 참조

---

## 관련 문서

- [scoring-data.md](scoring-data.md) — AIC scoring 기반 자동 평가
- [kinematic-signals.md](kinematic-signals.md) — kinematic 신호 기반 자동 평가
