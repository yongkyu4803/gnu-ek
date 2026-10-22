# Boltz 단백질 구조 예측

- 입력: 사용자가 제공한 서열 그대로, 381 aa, 단일 사슬 A. 리간드/금속/복합체는 지정하지 않았습니다.
- 모델: 공식 Boltz 2.2.1 패키지의 Boltz-2.
- GPU: NVIDIA GeForce RTX 3060, 12 GB VRAM.
- 환경: Python 3.11 전용 `.venv`, PyTorch 2.7.1 CUDA 12.6.
- 설정: GPU 1개, BF16 mixed precision (Boltz-2 기본값), recycling 3, sampling steps 200, diffusion samples 5, 한 번에 1개 샘플, seed 42.
- Windows 호환성: `--no_kernels`로 선택적 cuEquivariance 커널만 끕니다. 구조 계산은 CUDA GPU에서 실행합니다. 데이터 로더는 `num_workers=0`입니다.
- MSA: ColabFold 서버에서 생성한 2,148개 항목의 로컬 `msa/protein.a3m`을 사용합니다. 최초 Boltz 요청의 결과 다운로드 경로가 404를 반환하여 ColabFold 호환 요청으로 복구했습니다. 재실행 시 서열을 다시 전송할 필요가 없습니다.

## 실행

이 폴더에서 PowerShell로 실행:

```powershell
& .\.venv\Scripts\python.exe -u .\run_prediction.py *> prediction.log
```

`run_info.json`에 실행 상태, 환경, 설정, 소요 시간, GPU 최대 메모리 사용량이 기록됩니다. 이미 완성된 결과가 있으면 Boltz 기본 동작에 따라 재사용합니다.

## 파일

- `protein.fasta`, `protein.yaml`: 원본 서열 및 Boltz 입력
- `cache/`: 모델 가중치와 화학 성분 데이터
- `results/boltz_results_protein/predictions/protein/`: 모델 CIF, 신뢰도 JSON, 잔기별 pLDDT 및 PAE
- `prediction.log`: 실행 로그
- `prediction_msa_failed.log`: 최초 MSA 서버 다운로드 오류 기록
- `best_model.cif`, `best_model.pdb`: 완료 후 최고 신뢰도 모델 사본
- `RESULTS.md`, `model_confidence.csv`, `residue_confidence.csv`: 완료 후 검증 및 신뢰도 요약

예측 모델은 실험 구조가 아닙니다. pLDDT가 낮은 구간과 PAE가 높은 구간 사이의 상대 배치는 해석에 주의해야 합니다.

공식 안내: https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md
