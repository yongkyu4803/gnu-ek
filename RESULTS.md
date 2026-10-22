# Boltz-2 구조 예측 결과

사용자가 제공한 서열 381 aa를 단일 사슬 A로 예측했습니다. 5개 모델 모두 입력 서열과 좌표 유효성을 확인했습니다.
최고 신뢰도 모델: `protein_model_0` → `best_model.cif`, `best_model.pdb`.

| 모델 | confidence score | pTM | 평균 pLDDT (0–100) |
|---|---:|---:|---:|
| protein_model_0 | 0.6331 | 0.5606 | 65.12 |
| protein_model_1 | 0.6187 | 0.5501 | 63.58 |
| protein_model_2 | 0.6132 | 0.5511 | 62.87 |
| protein_model_3 | 0.6128 | 0.5526 | 62.79 |
| protein_model_4 | 0.6111 | 0.5535 | 62.56 |

최고 모델에서 pLDDT < 50인 잔기: 164/381.
최고 모델에서 pLDDT ≥ 70인 잔기: 182/381.

pLDDT가 낮은 부위의 모양이나 PAE가 높은 영역 사이의 상대 배치를 확정 구조로 해석하지 마세요. 단일 사슬이며 금속·리간드·다량체 조건을 지정하지 않았습니다.

GPU: NVIDIA GeForce RTX 3060; 최대 PyTorch 할당 메모리 5.16 GiB, 예약 메모리 6.86 GiB.
성공한 GPU 예측 실행 소요 시간: 2.5분 (최초 설치·모델 다운로드·MSA 복구 시간 제외).
PDB의 B-factor 필드는 실험적 온도 인자가 아니라 모델 신뢰도입니다.

설정과 재실행 방법: README.md. 잔기별 점수: residue_confidence.csv. 전체 PAE: 원본 predictions 폴더의 NPZ.
