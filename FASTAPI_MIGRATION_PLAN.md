# FastAPI 마이그레이션 계획

작성일: 2026-10-20  
대상: 현재 Tk GUI 기반 Boltz-2 배치 모델링 도구

## 1. 목표

현재의 단일 PC·단일 GPU 실행 특성을 유지하면서 데스크톱 GUI를 로컬 FastAPI 웹 애플리케이션으로 전환한다.

- 브라우저에서 `.seq` 입력, 배치 시작, 진행 확인, 중지, 결과 열람을 제공한다.
- 긴 GPU 작업을 HTTP 요청 수명과 분리한다.
- 파일별 순차 실행과 GPU 동시 작업 1개 제한을 유지한다.
- 서버 재시작 후에도 작업 상태와 완료 결과를 복구한다.
- 기존 `result/`와 manifest를 가능한 한 GPU 재계산 없이 가져온다.
- 기본 실행 범위는 로컬 PC의 `127.0.0.1`로 제한한다.

## 2. 이번 마이그레이션의 범위

### 포함

- FastAPI 기반 제어 API
- 로컬 웹 UI
- 배치 작업 큐와 상태 저장
- 실시간 로그 스트리밍
- 작업 중지와 렌더링 재시도
- 결과 이미지·CSV·JSON·PDB 다운로드
- 기존 결과 스캔 및 가져오기
- Windows 실행 스크립트와 브라우저 자동 열기

### 1차 범위에서 제외

- 인터넷에 공개되는 다중 사용자 서비스
- 계정, 권한, 결제, 조직 기능
- 여러 GPU 또는 여러 컴퓨터에 분산된 작업 큐
- ColabFold나 Boltz 자체를 별도 서버로 분리하는 작업
- React/Next.js 같은 별도 프런트엔드 빌드 체인
- 기존 과학 계산 설정 변경

초기 UI는 FastAPI가 정적 HTML/CSS/JavaScript를 함께 제공하는 구조를 권장한다. 기능이 안정된 뒤 별도 프런트엔드가 필요할 때 분리한다.

## 3. 선행 조건

FastAPI 전환 전에 `UPDATE_PLAN.md`의 다음 항목을 먼저 해결한다.

- [ ] `.venv`, CUDA, Boltz, 모델 cache에 대한 실행 전 진단
- [ ] `protein.yaml`과 결과 manifest의 절대경로 제거
- [ ] runner와 GUI가 함께 사용할 manifest 무결성 검증 함수
- [ ] MSA cache schema/version 및 손상 검증
- [ ] PyMOL이 없어도 PDB까지 저장되는 부분 성공 흐름

이 작업을 먼저 하는 이유는 웹 계층에 현재의 경로·캐시 결함을 그대로 복제하지 않기 위해서다.

## 4. 목표 아키텍처

```text
브라우저
  ├─ REST API: 작업 생성, 조회, 중지, 결과 목록
  └─ SSE: 상태와 로그 실시간 수신
            │
            ▼
FastAPI 애플리케이션
  ├─ API / 입력 검증
  ├─ Job service
  ├─ SQLite 상태 저장소
  ├─ 단일 GPU 작업 큐
  └─ Artifact service
            │
            ▼
기존 계산 계층
  ├─ FASTA/MSA/manifest 공용 로직
  ├─ 파일별 worker subprocess
  ├─ Boltz GPU subprocess
  └─ PyMOL subprocess
```

핵심 원칙:

- FastAPI endpoint 안에서 Boltz를 직접 실행하지 않는다.
- FastAPI `BackgroundTasks`를 장시간 GPU 작업 큐로 사용하지 않는다.
- 요청은 작업을 등록한 뒤 즉시 `202 Accepted`와 job ID를 반환한다.
- 실제 계산은 애플리케이션 수명 동안 실행되는 단일 supervisor가 담당한다.
- Boltz는 지금처럼 파일별 별도 subprocess에서 실행해 GPU 메모리를 반환한다.
- 상태의 기준은 메모리가 아니라 SQLite와 파일 manifest다.

## 5. 권장 디렉터리 구조

```text
app/
  __init__.py
  main.py                 # FastAPI 생성, lifespan, router 등록
  config.py               # data root, cache, host, port, 동시성
  api/
    jobs.py               # 작업 생성/조회/중지
    artifacts.py          # 안전한 결과 조회/다운로드
    health.py             # 환경·GPU·PyMOL 상태
  services/
    job_service.py        # 상태 전이와 작업 orchestration
    supervisor.py         # 단일 GPU 큐와 재시작 복구
    event_service.py      # 로그 저장 및 SSE fan-out
    artifact_service.py   # manifest 검증과 파일 허용 목록
    legacy_import.py      # 기존 result 폴더 가져오기
  repositories/
    sqlite.py
  schemas/
    jobs.py               # Pydantic request/response 모델
  web/
    index.html
    app.js
    styles.css
boltz_batch_core.py       # 계산 도메인 로직
boltz_batch_worker.py     # GPU worker
render_pymol.py
tests/
  unit/
  api/
  integration/
run_boltz_web.cmd
```

기존 `boltz_batch_gui.py`와 `boltz_batch_runner.py`는 마이그레이션 기간에 유지한다. 공용 로직을 추출한 뒤 두 진입점이 같은 서비스 계층을 사용하도록 한다.

## 6. 입력 방식 결정

브라우저는 데스크톱 Tk처럼 임의의 서버 폴더 선택 창을 직접 열 수 없다. 다음 두 입력 방식을 제공한다.

### 기본 방식: 파일 업로드

- 사용자가 하나 이상의 `.seq` 파일을 선택한다.
- 서버가 각 파일을 관리되는 job 입력 폴더로 복사한다.
- 파일명, 크기, 확장자, UTF-8, FASTA 내용을 서버에서 다시 검증한다.
- 동일 stem의 대소문자 충돌을 거부한다.

### 로컬 전용 보조 방식: 서버 폴더 가져오기

- 설정된 `data_root` 아래의 폴더만 선택할 수 있다.
- 브라우저가 임의의 절대경로를 API에 전달하는 방식은 사용하지 않는다.
- `Path.resolve()` 후 `data_root` 하위인지 검사한다.
- 심볼릭 링크와 `..`를 통한 탈출을 거부한다.

1차 구현은 업로드 방식부터 완료하고, 기존 폴더 기반 사용자가 필요할 때만 보조 방식을 추가한다.

## 7. 작업 및 상태 모델

### BatchJob

- `id`: UUID
- `created_at`, `started_at`, `finished_at`
- `status`
- `force`
- `render_requested`
- `input_count`
- `completed_count`, `partial_count`, `failed_count`, `cancelled_count`
- `error_summary`
- `settings_snapshot`

### JobItem

- `id`, `job_id`
- `source_name`, `safe_stem`
- `fingerprint`
- `status`
- `current_stage`
- `work_dir`, `manifest_path`
- `started_at`, `finished_at`
- `error_type`, `error_message`

### 상태 전이

```text
queued
  → validating
  → preparing_msa
  → predicting
  → validating_models
  → rendering
  → completed
              ↘ partial

어느 실행 상태에서나:
  → cancelling → cancelled
  → failed
```

규칙:

- 종료 상태는 `completed`, `partial`, `failed`, `cancelled`이다.
- 프로세스가 비정상 종료된 채 서버가 재시작되면 `recovering`을 거쳐 재사용 가능한 산출물을 검사한다.
- 검증된 Boltz 원본이 있으면 GPU 계산 없이 게시 또는 렌더링 단계부터 재개한다.
- 공개 결과가 완전하지 않으면 기존 manifest를 `completed`로 인정하지 않는다.

## 8. API 초안

모든 endpoint는 `/api/v1` 아래에 둔다.

### 환경

- `GET /health`
  - 서버, SQLite, 쓰기 권한, Python, Boltz, CUDA, GPU, PyMOL 상태
- `GET /settings`
  - 노출 가능한 계산 설정과 기능 플래그

### 작업

- `POST /jobs`
  - multipart `.seq` 업로드
  - `force`, `render` 옵션
  - 응답: `202 Accepted`, job ID
- `GET /jobs`
  - 최근 작업 목록과 집계
- `GET /jobs/{job_id}`
  - 작업 및 파일별 상태
- `POST /jobs/{job_id}/cancel`
  - idempotent 중지 요청
- `POST /jobs/{job_id}/retry-render`
  - GPU 재계산 없이 PyMOL 단계만 재시도
- `POST /jobs/{job_id}/retry-failed`
  - 실패 항목만 새 실행으로 재시도

### 이벤트와 결과

- `GET /jobs/{job_id}/events`
  - `text/event-stream` 형식의 SSE
  - `Last-Event-ID`로 재연결 시 누락 이벤트 재전송
- `GET /jobs/{job_id}/items/{item_id}/results`
  - manifest 기반 결과 목록
- `GET /jobs/{job_id}/items/{item_id}/artifacts/{artifact_id}`
  - 허용 목록에 있는 파일만 다운로드

서버 파일의 실제 절대경로를 API 응답에 포함하지 않는다.

## 9. 실시간 로그 방식

초기 버전은 WebSocket보다 SSE를 권장한다.

- 진행 데이터는 서버에서 브라우저로 흐르는 단방향 통신이 대부분이다.
- 브라우저의 `EventSource`가 자동 재연결을 제공한다.
- 프록시나 방화벽 환경에서 단순하다.
- 작업 제어는 기존 REST endpoint로 분리할 수 있다.

이벤트 예시:

```json
{
  "id": 152,
  "type": "item.status",
  "job_id": "...",
  "item_id": "...",
  "timestamp": "2026-10-20T15:00:00+09:00",
  "data": {"status": "predicting", "message": "Boltz-2 GPU 예측 중"}
}
```

구현 규칙:

- 이벤트를 SQLite에 먼저 기록한 뒤 연결된 SSE subscriber에게 전달한다.
- 느린 브라우저 때문에 worker 로그 읽기가 막히지 않도록 subscriber queue 크기를 제한한다.
- UI에는 최근 로그만 유지하고 전체 로그 파일은 artifact로 제공한다.
- ANSI escape sequence와 제어 문자를 제거한다.

## 10. 작업 실행과 중지

- supervisor는 기본적으로 실행 중인 GPU item을 1개로 제한한다.
- API 서버에 worker thread를 하나 두되, 실제 Boltz와 PyMOL은 subprocess로 실행한다.
- subprocess PID와 생성 시간을 SQLite에 기록한다.
- 중지 요청은 DB에 `cancel_requested_at`을 기록한 뒤 현재 process tree를 종료한다.
- Windows에서는 `taskkill /PID <pid> /T /F`를 사용하되 PID 재사용을 막기 위해 생성 시간을 확인한다.
- 서버 종료 시 새 작업을 받지 않고 현재 subprocess에 제한 시간 내 중지를 요청한다.
- 중지 후 검증된 중간 결과와 기존 공개 결과는 보존한다.

Uvicorn worker는 1개만 사용한다. 여러 Uvicorn worker를 실행하면 각 worker가 별도 supervisor를 만들어 단일 GPU 큐 보장이 깨지므로 시작 단계에서 차단하거나 supervisor를 별도 프로세스로 분리해야 한다.

## 11. 데이터 저장

### SQLite

권장 테이블:

- `jobs`
- `job_items`
- `events`
- `artifacts`
- `schema_migrations`

설정:

- WAL 모드
- foreign key 활성화
- 짧은 트랜잭션
- DB 쓰기는 repository 계층에서 직렬화

### 파일 시스템

```text
data/
  app.db
  jobs/
    <job-id>/
      input/
      work/
      result/
      logs/
```

- DB에는 상태와 상대경로만 저장한다.
- PDB, CIF, NPZ, PNG, PSE처럼 큰 파일은 파일 시스템에 둔다.
- artifact는 manifest에 등록된 상대경로와 체크섬이 일치할 때만 제공한다.
- HTTP 다운로드 파일명은 안전한 ASCII fallback과 UTF-8 이름을 함께 제공한다.

## 12. 보안 기준

로컬 애플리케이션이어도 다음 기준을 적용한다.

- 기본 bind 주소는 `127.0.0.1`이다.
- CORS는 기본 비활성화한다.
- Swagger 문서는 로컬에서만 사용한다.
- 업로드 크기, 파일 수, 서열 길이, chain 수에 상한을 둔다.
- 업로드 파일명은 표시용으로만 보존하고 저장 경로에는 UUID를 사용한다.
- `Path.resolve()`와 허용된 root 검사를 모든 파일 접근에 적용한다.
- artifact endpoint에서 임의 경로나 query 기반 파일 열기를 허용하지 않는다.
- 로그와 API 응답에 로컬 절대경로, 환경변수, 토큰을 노출하지 않는다.
- 외부 접속을 허용하는 단계에서는 인증과 TLS를 별도 설계한 뒤 진행한다.

## 13. 단계별 실행 계획

### Phase 0: 회귀 테스트와 기준선 고정

- [ ] 현재 7개 단위 테스트를 `tests/unit/` 구조로 이전한다.
- [ ] manifest, cache, cancel, publish에 대한 실패 재현 테스트를 추가한다.
- [ ] 기존 `batch_smoke_events.jsonl`을 API 계약 fixture가 아니라 참고 자료로 분리한다.
- [ ] 현재 출력 형식과 과학 계산 설정을 snapshot으로 기록한다.

완료 조건: 계산 로직을 이동해도 기존 동작 변화가 테스트에서 탐지된다.

### Phase 1: 프레임워크와 무관한 서비스 계층 추출

- [ ] `Batch.one()`의 계산 orchestration을 `JobService` 또는 공용 runner로 분리한다.
- [ ] `emit()` 의존성을 event sink 인터페이스로 교체한다.
- [ ] Tk stdout JSON, FastAPI DB/SSE가 각각 event sink를 구현한다.
- [ ] manifest 검증과 artifact 목록 생성을 공용 함수로 만든다.
- [ ] subprocess 실행과 process tree 중지를 공용 executor로 분리한다.

완료 조건: Tk GUI가 새 서비스 계층을 사용하면서 기존 단위 테스트가 통과한다.

### Phase 2: SQLite 상태 저장과 supervisor

- [ ] schema와 migration runner를 추가한다.
- [ ] job/item 생성, 상태 전이, 이벤트 append repository를 구현한다.
- [ ] 단일 GPU queue supervisor를 구현한다.
- [ ] 중복 실행 방지를 위한 DB lease 또는 단일 인스턴스 lock을 추가한다.
- [ ] 시작 시 `predicting` 등 비종료 상태의 작업을 복구한다.

완료 조건: 서버를 계산 중 강제 종료한 뒤 다시 시작해 상태가 `recovering` 또는 명확한 실패 상태로 정리된다.

### Phase 3: FastAPI API

- [ ] lifespan에서 환경 검사, DB, supervisor를 시작·종료한다.
- [ ] health, jobs, cancel, retry endpoint를 구현한다.
- [ ] Pydantic response schema와 일관된 오류 형식을 정의한다.
- [ ] SSE endpoint와 `Last-Event-ID` 복구를 구현한다.
- [ ] 안전한 artifact download endpoint를 구현한다.

완료 조건: 브라우저 없이 API만으로 업로드부터 결과 다운로드까지 수행할 수 있다.

### Phase 4: 웹 UI

- [ ] `.seq` 다중 업로드와 입력 미리보기를 제공한다.
- [ ] 작업·파일별 상태와 전체 progress를 표시한다.
- [ ] 실시간 로그, 중지, 실패 항목 재시도 버튼을 제공한다.
- [ ] 중첩 이미지와 confidence/pLDDT/pTM/ipTM/RMSD 표를 표시한다.
- [ ] PDB, aligned PDB, CSV, JSON, PNG, PSE 다운로드 링크를 제공한다.
- [ ] partial, failed, cancelled 상태를 색상뿐 아니라 텍스트로 구분한다.

완료 조건: 기존 Tk 화면의 주요 기능을 브라우저에서 수행할 수 있다.

### Phase 5: 기존 결과 가져오기

- [ ] 지정된 legacy 폴더를 읽기 전용으로 스캔한다.
- [ ] fingerprint, 체크섬, schema를 검증한다.
- [ ] 절대 이미지 경로를 상대 artifact로 마이그레이션한다.
- [ ] 유효한 결과는 `completed`, 이미지 없는 결과는 `partial`로 등록한다.
- [ ] 원본 파일을 수정하지 않는 dry-run 보고서를 먼저 제공한다.

완료 조건: 기존 결과가 GPU 재계산 없이 웹 UI에 표시된다.

### Phase 6: Windows 패키징과 병행 운영

- [ ] `run_boltz_web.cmd`에서 환경 검사 후 Uvicorn을 worker 1개로 실행한다.
- [ ] 준비 완료 후 기본 브라우저를 연다.
- [ ] 포트 충돌과 이미 실행 중인 서버를 감지한다.
- [ ] Tk GUI와 웹 UI를 한 릴리스 동안 함께 제공한다.
- [ ] 기능 동등성과 사용자 확인 후 Tk GUI를 deprecated로 표시한다.

완료 조건: 더블클릭 한 번으로 로컬 서버와 웹 UI가 시작되고 종료 절차가 명확하다.

## 14. 테스트 계획

### 단위 테스트

- FASTA 및 업로드 검증
- 상태 전이의 허용·거부 조합
- manifest 이식성 및 체크섬
- MSA cache key/schema
- artifact path traversal 차단
- process cancel과 PID 생성 시간 검증
- legacy manifest 변환

### API 테스트

- 정상 업로드와 `202` 응답
- 확장자, 크기, FASTA 오류 응답
- job 목록·상세·중지 idempotency
- SSE 이벤트 순서와 재연결
- 없는 job/item/artifact의 오류 형식
- 완료되지 않은 artifact 접근 차단
- API 응답에 절대경로가 없는지 확인

### 서비스 통합 테스트

- 가짜 worker subprocess로 성공, 실패, timeout, cancel 재현
- 서버 재시작 후 queued/running job 복구
- 여러 job 제출 시 GPU item이 동시에 두 개 실행되지 않는지 확인
- 렌더링 실패가 `partial`로 끝나는지 확인
- 기존 결과를 가져올 때 GPU worker가 호출되지 않는지 확인

### Windows 인수 테스트

- 한글·공백이 포함된 경로
- RTX 3060에서 실제 2-chain smoke test
- PyMOL 설치/미설치 두 환경
- 브라우저 새로고침과 서버 재시작
- 작업 중 중지와 앱 종료
- 결과 폴더 이동 후 legacy import

## 15. 의존성 계획

추가 후보:

- `fastapi`
- `uvicorn[standard]`
- `pydantic`
- `python-multipart`
- 테스트용 `httpx`

주의 사항:

- Python 3.11과 호환되는 버전을 고정한다.
- Boltz/PyTorch 환경과 웹 의존성의 충돌을 깨끗한 가상환경에서 검증한다.
- FastAPI와 Pydantic major version을 명시한다.
- 장시간 작업을 위해 Celery/Redis를 즉시 추가하지 않는다. 단일 PC·단일 GPU 단계에서는 SQLite supervisor가 운영 복잡도가 낮다.

## 16. 배포 및 운영 설정

기본 설정 예시:

```text
BOLTZ_APP_HOST=127.0.0.1
BOLTZ_APP_PORT=8765
BOLTZ_APP_DATA_DIR=<설치폴더>/data
BOLTZ_MODEL_CACHE=<설치폴더>/cache
BOLTZ_GPU_CONCURRENCY=1
BOLTZ_PYMOL_EXE=<자동 탐색 또는 사용자 지정>
```

- 환경변수에는 기본값을 두되 UI/API에 비밀값을 노출하지 않는다.
- 설정 스냅샷을 각 job에 저장해 결과 재현성을 유지한다.
- health endpoint는 준비 상태와 상세 진단을 구분한다.
- 로그 rotation과 오래된 이벤트 정리 정책을 추가한다.
- 결과 삭제 기능은 초기 버전에 넣지 않고, 추가 시 명시적 확인과 복구 정책을 설계한다.

## 17. 권장 커밋 순서

1. 테스트 구조와 회귀 fixture
2. manifest·경로·MSA cache 선행 수정
3. event sink 및 공용 executor 추출
4. SQLite schema와 repository
5. supervisor와 재시작 복구
6. FastAPI health/jobs API
7. SSE와 artifact API
8. 로컬 웹 UI
9. legacy import
10. Windows launcher와 문서
11. 실제 GPU/PyMOL 인수 검증

각 커밋은 GPU가 없는 환경에서도 가능한 테스트를 통과해야 한다. 데이터 schema 변경에는 migration과 rollback 또는 재생성 전략을 함께 포함한다.

## 18. 주요 위험과 대응

- **HTTP 요청에서 GPU 작업을 직접 실행하는 위험:** job 등록과 supervisor 실행을 분리한다.
- **Uvicorn 다중 worker로 GPU 작업이 중복되는 위험:** worker 1개를 강제하고 단일 인스턴스 lease를 둔다.
- **서버 재시작으로 상태를 잃는 위험:** 상태와 이벤트를 SQLite에 먼저 기록한다.
- **브라우저를 통한 임의 파일 접근 위험:** 관리 root와 artifact ID만 허용한다.
- **업로드 대용량으로 메모리를 소모하는 위험:** streaming 저장, 파일 수·크기 제한을 적용한다.
- **기존 결과 마이그레이션이 GPU 재계산을 일으키는 위험:** dry-run과 체크섬 기반 import를 우선한다.
- **Tk와 웹 실행이 동시에 같은 결과를 변경하는 위험:** 공용 lock/lease를 사용하고 동일 data root의 동시 실행을 거부한다.
- **SSE 연결이 끊겨 로그가 사라지는 위험:** 이벤트 ID를 DB에 저장하고 재연결 시 재전송한다.

## 19. 최종 완료 정의

- `run_boltz_web.cmd`로 로컬 웹 UI를 시작할 수 있다.
- 여러 `.seq` 파일을 업로드하고 파일별 순차 GPU 예측을 수행할 수 있다.
- 실시간 로그, 진행률, 중지, 실패 표시가 브라우저 새로고침 후에도 유지된다.
- 같은 GPU에서 예측 subprocess가 동시에 두 개 실행되지 않는다.
- 서버 재시작 후 작업과 결과 상태가 일관되게 복구된다.
- PyMOL이 없어도 PDB와 평가표를 받을 수 있고 나중에 렌더링만 재시도할 수 있다.
- 기존 유효 결과가 GPU 재계산 없이 가져와진다.
- API에서 임의 로컬 파일을 읽을 수 없고 절대경로가 노출되지 않는다.
- CPU 단위/API/통합 테스트와 Windows CUDA/PyMOL 인수 테스트가 통과한다.
- 한 릴리스 동안 Tk GUI와 FastAPI UI의 기능 동등성을 확인한 뒤 전환 여부를 결정한다.
