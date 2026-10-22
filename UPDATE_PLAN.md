# Boltz Batch 업데이트 계획

작성일: 2026-10-20  
대상: 현재 폴더의 Boltz-2 단일 예측 및 Windows 배치 GUI 코드

## 목표

현재 계산 설정과 결과 형식을 유지하면서 다음 상태를 만든다.

- 새 위치에 복사한 폴더에서도 실행과 결과 재사용이 가능하다.
- 누락된 실행 환경이나 모델 캐시를 시작 단계에서 명확히 진단한다.
- GUI와 배치 실행기가 동일한 기준으로 결과 무결성을 판정한다.
- MSA 설정이 바뀌면 이전 MSA 캐시가 새 결과에 섞이지 않는다.
- PyMOL이 없어도 캐시 재사용 또는 PDB 생성까지는 진행할 수 있다.
- GPU 없이 실행 가능한 회귀 테스트와 GPU 통합 테스트를 구분한다.

## 유지해야 할 동작

- Boltz 2.2.1, recycling 3, sampling steps 200, diffusion samples 5, seed 42
- 파일별 순차 처리와 독립 GPU 프로세스
- 입력 파일당 5개 모델을 `confidence_score` 순으로 게시
- chain A 전체 Cα 기준 정렬과 복합체 전체의 동일 강체 변환
- 강제 재계산 실패 시 기존 공개 결과 보존
- ColabFold 전송 사실을 실행 전과 로그에서 계속 고지

## 우선순위 요약

| 순서 | 우선순위 | 작업 | 완료 결과 |
|---:|:---:|---|---|
| 1 | P1 | 실행 환경과 경로 복구 | 새 폴더에서 예측을 시작하거나 정확한 설치 안내를 받음 |
| 2 | P1 | manifest 이식성과 검증 통합 | 이동·복사·파일 손상 시 올바른 상태를 표시함 |
| 3 | P2 | MSA 캐시 버전 및 무결성 강화 | 설정 변경이나 손상된 캐시를 재사용하지 않음 |
| 4 | P2 | PyMOL 선택 의존성 처리 | PyMOL 없이 캐시/PDB 경로가 동작함 |
| 5 | P2 | 테스트 자산과 자동 검증 복구 | CPU 회귀 테스트와 GPU 통합 테스트를 재현 가능하게 실행함 |
| 6 | P3 | 문서와 배포 파일 정리 | 실제 배포 내용과 사용 설명이 일치함 |

## 1단계: 실행 가능한 기준선 복구

대상 파일: `run_boltz_batch.cmd`, `run_prediction.py`, `protein.yaml`, `BATCH_README.md`, `README.md`, `requirements_lock.txt`

- [ ] 배포 방식을 하나로 확정한다.
  - 권장: `.venv` 자체를 복사하지 않고 Python 3.11 가상환경을 만드는 설치 스크립트와 검증된 의존성 설치 명령을 제공한다.
  - 모델 `cache/`를 배포하지 않는다면 최초 다운로드에 필요한 네트워크·용량·예상 동작을 문서화한다.
- [ ] `run_boltz_batch.cmd`에 시작 전 검사를 추가한다.
  - Python 실행 파일, 필수 모듈, 쓰기 가능한 작업 폴더를 확인한다.
  - 실패 시 누락 항목과 다음 명령을 출력하고 비정상 종료한다.
- [ ] `protein.yaml`의 `D:\G박사\boltz_data\...` 절대경로 의존성을 제거한다.
  - `run_prediction.py`가 실행 시 현재 `ROOT`를 기준으로 임시 입력 YAML을 생성하도록 한다.
  - 원본 서열과 사용자 설정 파일은 수정하지 않는다.
- [ ] CUDA를 사용할 수 없을 때 기존처럼 CPU로 묵시 전환하지 않되, GPU·드라이버·Torch 상태를 한 번에 진단한다.
- [ ] `torch==2.7.1+cu126` 설치에 필요한 패키지 인덱스 또는 설치 스크립트를 명시한다.

완료 조건:

- 경로에 한글과 공백이 있는 새 Windows 폴더에서 실행된다.
- `.venv`, 모델 캐시 또는 CUDA가 없으면 사용자가 해결할 수 있는 오류 메시지를 제공한다.
- 단일 예측 입력 파일에 과거 컴퓨터의 절대경로가 남지 않는다.

## 2단계: manifest 이식성과 결과 검증 통합

대상 파일: `boltz_batch_runner.py`, `boltz_batch_gui.py`, `boltz_batch_core.py`, `test_boltz_batch.py`

- [ ] manifest에 `schema_version`을 추가한다.
- [ ] `image`를 포함한 모든 게시 파일 경로를 `result/` 기준 상대경로로 저장한다.
- [ ] manifest 읽기와 검증을 공용 함수로 분리한다.
  - fingerprint 일치
  - `rendered` 상태
  - 선언된 파일 존재 여부
  - SHA-256 체크섬
  - `result/` 밖으로 벗어나는 경로 거부
- [ ] GUI의 폴더 스캔도 공용 검증 함수를 사용한다.
  - 완전한 결과: `완료된 결과`
  - PDB만 유효: `PDB 완료 / 이미지 없음`
  - 체크섬 불일치 또는 누락: `결과 손상 / 재생성 필요`
- [ ] 기존 manifest를 위한 호환 처리를 추가한다.
  - 기존 절대 `image` 값은 현재 `result/images/<파일명>`으로 안전하게 재해석한다.
  - 기존 결과의 체크섬이 맞으면 GPU 재계산 없이 새 manifest로 갱신한다.
  - Windows 역슬래시 상대경로도 정규화하되 상위 디렉터리 이동은 허용하지 않는다.

완료 조건:

- 결과 폴더를 다른 위치로 복사해도 이미지와 점수표가 표시된다.
- PDB 또는 이미지 하나를 변조·삭제하면 GUI와 runner가 모두 재사용을 거부한다.
- legacy 결과를 옮겼다는 이유만으로 GPU 예측을 다시 수행하지 않는다.

## 3단계: MSA 캐시 버전 및 무결성 강화

대상 파일: `boltz_batch_core.py`, `boltz_batch_worker.py`, `test_boltz_batch.py`

- [ ] MSA 캐시 키에 다음 값을 포함한다.
  - 순서가 보존된 고유 서열 목록
  - MSA schema/version (`SETTINGS["msa"]`)
  - paired/unpaired 모드와 행 제한
- [ ] 캐시된 entity CSV를 재사용하기 전에 검증한다.
  - 헤더가 `key,sequence`인지 확인
  - query 행과 입력 서열 일치 확인
  - A3M 정렬 길이 및 허용 문자 확인
  - paired key 형식 확인
- [ ] 모든 entity 파일이 성공적으로 저장된 뒤 completion metadata를 원자적으로 기록한다.
- [ ] 손상되거나 구버전인 캐시는 별도 보관하거나 명시적으로 무시하고 다시 생성한다.
- [ ] 로그에 cache hit/miss 이유와 MSA schema를 기록한다.

완료 조건:

- MSA 버전 문자열만 바꿔도 기존 캐시를 재사용하지 않는다.
- 완성된 것처럼 보이는 빈 CSV나 잘린 CSV를 입력으로 사용하지 않는다.
- 동일 입력과 동일 설정에서는 네트워크 요청 없이 정상 재사용한다.

## 4단계: PyMOL 선택 의존성 및 부분 성공 처리

대상 파일: `boltz_batch_gui.py`, `boltz_batch_runner.py`, `BATCH_README.md`

- [ ] GUI 시작 단계의 PyMOL 강제 차단을 제거한다.
- [ ] PyMOL이 없을 때의 동작을 명확히 구분한다.
  - 완전한 캐시: 그대로 재사용
  - 검증된 Boltz CIF 존재: PDB/평가표 게시 후 이미지 없음 상태
  - 새 예측: GPU 예측과 PDB 게시까지 진행 후 이미지 없음 상태
- [ ] 사용자가 PyMOL 경로를 나중에 지정하면 GPU 재계산 없이 렌더링만 다시 실행한다.
- [ ] GUI 종료 코드와 요약에서 `failed`와 `partial`을 별도로 설명한다.

완료 조건:

- PyMOL이 없는 환경에서도 유효한 캐시를 재확인할 수 있다.
- 새 예측의 PDB 5개와 평가표가 보존된다.
- PyMOL을 설치한 뒤 렌더링만 재시도할 수 있다.

## 5단계: 테스트와 검증 자산 복구

대상 파일: `test_boltz_batch.py`, `verify_batch_outputs.py`, `batch_examples/`, 신규 테스트 fixture

### CPU에서 항상 실행할 테스트

- [ ] FASTA 정상·오류·62 chain 경계
- [ ] fingerprint 및 MSA cache key 변경 조건
- [ ] 손상·누락·이동된 manifest 검증
- [ ] legacy 절대경로 manifest 마이그레이션
- [ ] 강제 재계산 실패 시 기존 결과 보존
- [ ] PyMOL 미설치 상태의 cached/partial 분기
- [ ] 중지 marker, stale lock, 파일명 대소문자 충돌
- [ ] MSA CSV 손상과 불완전 completion metadata 거부

### 선택적 통합 테스트

- [ ] 문서가 언급하는 `batch_examples/complex_demo.seq`를 복구한다.
- [ ] 큰 바이너리 결과를 저장소에 넣지 않는 경우 작은 합성 CIF/PDB fixture로 게시·정렬 전 단계까지 검증한다.
- [ ] PyMOL 설치 환경에서 강체 변환, RMSD, PNG/PSE 생성을 검증한다.
- [ ] CUDA 환경에서 별도 표식이 있는 실제 Boltz smoke test를 실행한다.
- [ ] GPU 테스트는 비용이 큰 일반 단위 테스트와 분리한다.

필수 검증 명령의 목표 형태:

```powershell
& .\.venv\Scripts\python.exe -m unittest -v test_boltz_batch.py
& .\.venv\Scripts\python.exe verify_batch_outputs.py
```

완료 조건:

- CPU 단위 테스트는 네트워크, CUDA, PyMOL 없이 통과한다.
- 통합 테스트에 필요한 fixture가 실제 배포본에 존재한다.
- GPU smoke test의 실행 조건과 예상 산출물이 문서화된다.

## 6단계: 문서와 배포 정리

대상 파일: `README.md`, `BATCH_README.md`, 신규 설치 문서 또는 스크립트

- [ ] 단일 예측과 배치 GUI의 목적·실행 방법을 분리해 설명한다.
- [ ] 실제 포함 파일과 선택 다운로드 파일을 구분한다.
- [ ] Python, CUDA, Torch, Boltz, PyMOL 지원 버전을 명시한다.
- [ ] 재사용, 부분 성공, 결과 손상, MSA 재생성 상태를 설명한다.
- [ ] MSA가 외부 ColabFold 서비스로 전송된다는 고지를 유지한다.
- [ ] 절대경로가 들어 있는 과거 로그는 예시 자료임을 표시하거나 배포본에서 제외한다.
- [ ] 생성물과 비밀·대용량 파일을 위한 `.gitignore`를 추가한다.

## 권장 구현 순서

1. 테스트 fixture와 실패 재현 테스트부터 추가한다.
2. 실행 전 검사와 단일 예측의 절대경로를 수정한다.
3. 공용 manifest 검증기와 legacy 마이그레이션을 구현한다.
4. GUI를 공용 검증기에 연결한다.
5. MSA cache key/schema와 CSV 검증을 추가한다.
6. PyMOL 부분 성공 흐름을 GUI에 연결한다.
7. Windows/PyMOL/GPU 통합 테스트 후 문서를 갱신한다.

각 단계는 독립 커밋으로 유지하고, 데이터 형식 변경 커밋에는 해당 마이그레이션 테스트를 함께 포함한다.

## 위험과 대응

- **MSA 캐시 무효화로 외부 전송이 다시 발생할 수 있음:** 실행 전에 사용자에게 알리고 schema 변경 시에만 한 번 재생성한다.
- **manifest 변경이 불필요한 GPU 재계산을 유발할 수 있음:** 기존 파일 체크섬이 유효하면 manifest와 렌더링만 갱신한다.
- **Windows 경로 정규화가 기존 결과를 놓칠 수 있음:** 드라이브 문자, 역슬래시, 한글, 공백을 포함한 이동 테스트를 추가한다.
- **대용량 모델 캐시를 배포하기 어려움:** 코드 배포와 모델 다운로드 캐시를 분리하고 최초 실행 절차를 자동화한다.
- **실제 GPU 결과가 라이브러리 버전에 따라 달라질 수 있음:** 좌표 자체의 완전 일치 대신 모델 수, 구조 유효성, 서열, 유한 좌표, 점수 범위를 검증한다.

## 최종 완료 정의

- 깨끗한 Windows 환경에서 문서만 보고 설치와 실행을 완료할 수 있다.
- 폴더 이동 후에도 기존 결과가 GPU 재계산 없이 정상 표시된다.
- 손상된 출력이나 잘못된 MSA 캐시는 재사용되지 않는다.
- PyMOL 부재가 구조 예측 결과의 저장을 막지 않는다.
- CPU 회귀 테스트 전체와 Windows PyMOL 통합 테스트가 통과한다.
- 최소 1개의 실제 CUDA Boltz smoke test 결과가 남아 있다.
- README의 파일 목록과 실제 배포 파일이 일치한다.
