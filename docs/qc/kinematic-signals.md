# Kinematic 신호 기반 자동 평가

`tags.json` 같은 외부 scoring 데이터 없이, LeRobot parquet에 저장된 `action` / `observation.state` / `timestamp`만으로 에피소드 품질을 평가하는 방법입니다.

---

## 적용 대상

scoring 데이터를 연결할 수 없는 데이터셋에 사용합니다.

- `Serial_number` 컬럼이 없는 경우
- `Serial_number`가 있어도 원본 trial 폴더와 날짜가 불일치하는 경우
- `tags.json`의 success 필드가 `unknown`인 경우

---

## 사용 가능한 신호

### 1. Jerk (움직임 부드러움)

```python
vel   = np.diff(action, axis=0) * fps
accel = np.diff(vel,    axis=0) * fps
jerk  = np.diff(accel,  axis=0) * fps
mean_jerk = float(np.mean(np.linalg.norm(jerk, axis=1)))
```

낮을수록 부드럽고 안정적인 움직임입니다.

실측 범위 (dfs/ 데이터셋, fps=20 기준):

| 데이터셋 | jerk 범위 | 비고 |
|----------|-----------|------|
| `basic_aic_cheetcode_dataset` | 0.83 ~ 23.61 | 6DoF |
| `changyong` | 0.96 ~ 23.85 | 6DoF |
| `hojun` | 1.13 ~ 10.57 | 7DoF |
| `jjhyeongg` | 6.74 ~ 24.07 | 7DoF |
| `hrchung` | 0.07 ~ 0.10 | fps=5, 직접 비교 불가 |

27배 이상의 범위 차이로 데이터셋 내 구분 신호로 충분히 유효합니다.

> fps가 다른 데이터셋끼리 jerk를 직접 비교하면 안 됩니다.
> 반드시 **같은 데이터셋 내** 상대 비교만 하세요.

### 2. Duration (소요 시간)

```python
duration = float(timestamp[-1] - timestamp[0])
```

같은 태스크에서 짧을수록 효율적입니다.

| 데이터셋 | duration 범위 |
|----------|--------------|
| `basic_aic_cheetcode_dataset` | 31.6 ~ 33.3s |
| `changyong` | 47.2 ~ 60.5s |
| `hojun` | 32.2 ~ 51.5s |
| `jjhyeongg` | 12.1 ~ 18.2s |

### 3. Mean Velocity (평균 속도)

```python
vel = np.diff(action, axis=0) * fps
mean_vel = float(np.mean(np.linalg.norm(vel, axis=1)))
```

거의 0에 가까우면 로봇이 움직이지 않은 에피소드입니다 (stuck 감지).

### 4. F/T 신호 (hojun 데이터셋 한정)

`hojun`의 `observation.state`는 21차원으로, 7번째 이후 차원에 velocity 및 기타 상태 정보가 포함됩니다. 과도한 힘/충격 구간 감지에 활용할 수 있습니다.

---

## 등급 결정 전략

scoring 데이터 없이는 절대 기준이 없으므로, 데이터셋 내 **상대적 퍼센타일**로 등급을 정합니다.

```python
import numpy as np

def assign_grades_by_percentile(episode_jerks: list[float]) -> list[str]:
    """
    하위 33% = Good, 중간 33% = Normal, 상위 33% = Bad
    """
    jerks = np.array(episode_jerks)
    p33 = np.percentile(jerks, 33)
    p67 = np.percentile(jerks, 67)

    grades = []
    for j in jerks:
        if j <= p33:
            grades.append("Good")
        elif j <= p67:
            grades.append("Normal")
        else:
            grades.append("Bad")
    return grades
```

jerk와 duration을 결합하면 신뢰도를 높일 수 있습니다:

```python
# 복합 점수 (낮을수록 좋음)
score = 0.7 * jerk_normalized + 0.3 * duration_normalized
```

---

## 한계

| 한계 | 설명 |
|------|------|
| 성공/실패 판별 불가 | 삽입 성공 여부를 kinematic만으로 판단하기 어려움 |
| 태스크 의존성 | 같은 jerk라도 태스크에 따라 의미가 다름 |
| fps 의존성 | fps가 다른 데이터셋끼리 절대값 비교 불가 |
| 소규모 데이터셋 | 에피소드 수가 적으면(hojun: 6개) 퍼센타일 기준이 불안정 |

---

## 권고 워크플로우

```
1. 전체 에피소드 kinematic 지표 계산
        ↓
2. 퍼센타일 기반 자동 등급 초안 생성 → sidecar JSON에 저장
        ↓
3. curation-tools UI에서 영상 + ScalarChart 보며 경계선 케이스 검수
        ↓
4. 필요한 에피소드만 수동으로 등급 수정
```

Bad 초안 에피소드를 우선 확인해 검수 시간을 줄일 수 있습니다.
