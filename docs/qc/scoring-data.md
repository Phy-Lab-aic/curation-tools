# AIC Scoring 데이터 기반 자동 평가

AIC 엔진이 생성하는 `tags.json` / `scoring.yaml`을 이용해 에피소드 등급을 자동으로 부여하는 방법입니다.

---

## 전제 조건

- 원본 trial 폴더(`trial_N_scoreNNN/`)에 `tags.json`이 존재해야 합니다.
- `~/aic_community_e2e/`의 `tags.json` 구조를 기준으로 합니다.

---

## scoring 구조

AIC 채점은 3단계 tier로 구성됩니다.

```
총점 = tier_1(1점) + tier_2(0~25점) + tier_3(75점)
```

| tier | 내용 | 등급 결정 역할 |
|------|------|----------------|
| tier_1 | 모델 유효성 검사 (1 or 0) | 0이면 Bad |
| tier_2 | 궤적 품질 (duration, smoothness, efficiency, contacts, insertion_force) | Good/Normal 구분 |
| tier_3 | 삽입 성공 여부 (75 or 0) | 0이면 Bad |

`tags.json`에서 바로 읽을 수 있는 필드:

```json
{
  "success": true,
  "scoring": {
    "total": 96.43,
    "tier_3_score": 75
  }
}
```

tier_2는 `tags.json`만으로 역산할 수 있습니다:

```
tier_2 = total - tier_1(1) - tier_3_score
```

실측 통계 (`~/aic_community_e2e/`, 358 trials):

| 항목 | 값 |
|------|-----|
| 전체 성공률 | 80.2% (287/358) |
| 성공 시 총점 범위 | 95.5 ~ 96.5 |
| 성공 시 tier_2 범위 | 19.46 ~ 20.51 |
| 실패 시 tier_3_score | 0 |

---

## 등급 결정 로직

```python
def compute_grade(tags_path: Path) -> str:
    """tags.json을 읽어 Good / Normal / Bad 를 반환합니다."""
    if not tags_path.exists():
        return ""

    tags = json.loads(tags_path.read_text())
    scoring = tags.get("scoring", {})

    # Bad: 삽입 실패
    if not tags.get("success", False):
        return "Bad"

    # tier_2 역산 (tier_1은 성공 시 항상 1점)
    tier_2 = scoring.get("total", 0) - 1 - scoring.get("tier_3_score", 0)

    # Good: 성공 + 궤적 품질 상위
    if tier_2 >= 20.0:
        return "Good"

    return "Normal"
```

> **임계값 주의**: `tier_2 >= 20.0`은 cheatcode policy 실측 기준입니다.
> 학습 policy의 tier_2 분포를 확인한 후 조정이 필요합니다.

`scoring.yaml`까지 읽으면 더 세밀한 판단이 가능합니다:

| 조건 | 처리 |
|------|------|
| `contacts > 0` | 비정상 접촉 → Bad로 강등 검토 |
| `insertion_force > 0` | 과도한 삽입력 → Normal로 강등 검토 |

---

## 변환 파이프라인 연동

`rosbag-to-lerobot/src/main.py`의 변환 루프에 아래와 같이 추가합니다.

```python
# main.py run_conversion() 내부, custom_metadata 생성 직전에 추가

tags_path = input_path / folder_name / "tags.json"
auto_grade = compute_grade(tags_path)          # 위 함수 사용

custom_metadata = {
    "Serial_number": folder_name,
    "tags": metadata.get("tags", []),
    "grade": auto_grade,                        # 기존의 "" 대신 자동 등급
}
```

> **timing**: 변환 완료 후 원본 폴더가 `processed/`로 이동됩니다.
> `tags.json` 읽기는 반드시 이동 전에 해야 합니다.

---

## 사용자 수동 override

자동 등급은 parquet의 `grade` 컬럼에 저장됩니다.
curation-tools에서 사용자가 등급을 수정하면 사이드카 JSON에 별도 저장되며,
사이드카가 parquet보다 우선하므로 수동 교정이 자동 등급 위에 자연스럽게 쌓입니다.

```
parquet grade: "Normal"  (변환 시 자동 부여)
sidecar grade: "Good"    (사용자가 검수 후 수정)
→ UI에 표시되는 등급: "Good"
```
