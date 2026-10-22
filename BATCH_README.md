# Boltz Batch 사용법

## 시작

`run_boltz_batch.cmd`를 더블클릭하고 **폴더 선택 → 전체 모델링 시작**을 누르세요.
기존 `boltz_data/.venv`와 `boltz_data/cache`를 사용하므로 추가 설치가 필요하지 않습니다.
PyMOL은 이 컴퓨터에 설치된 실행 파일을 자동으로 찾습니다. 찾지 못하면 화면의 `pymol.exe 지정`으로 선택하세요.

왼쪽에는 폴더와 `.seq` 파일 목록/상태, 오른쪽에는 실시간 로그와 선택한 파일의 중첩 이미지/평가표가 표시됩니다.
다른 파일을 클릭하면 그 파일의 저장된 결과를 다시 볼 수 있습니다.

선택한 폴더 **바로 아래**의 `.seq` 파일을 이름순으로 처리합니다. 하위 폴더는 검색하지 않습니다.
프로그램 시작 시 기본 폴더는 현재 작업 폴더입니다. 특정 폴더를 지정하려면:

```powershell
& 'D:\G박사\boltz_data\.venv\Scripts\python.exe' 'D:\G박사\boltz_data\boltz_batch_gui.py' 'D:\내서열폴더'
```

## 입력

각 `.seq`는 UTF-8 FASTA 파일입니다. 한 FASTA 항목은 한 단백질 chain입니다.
같은 파일의 항목들은 **하나의 복합체로** 함께 예측합니다.

```text
>my_protein_A
ACDEFGHIKLMNPQRSTVWY
>my_protein_B
MKWVTFISLLFLFSSAYS
```

- FASTA 순서대로 chain A, B, C…를 부여합니다. 헤더는 원래 이름을 기록하는 용도로 사용합니다.
- 같은 서열을 두 번 적으면 같은 단백질의 두 chain으로 처리합니다.
- 여러 줄 서열, 공백, 소문자를 처리합니다. 빈 서열, FASTA 헤더 누락, 숫자, `*`, gap, B/Z/J/U/O 등은 오류로 표시합니다. 표준 20종 아미노산과 X를 지원합니다.
- PDB의 단일 문자 chain ID를 위해 최대 62 chains입니다. GPU에서 가능한 크기는 전체 잔기 수와 MSA 등에 따라 달라집니다.
- DNA/RNA/리간드/금속은 이 FASTA 전용 화면의 입력 대상이 아닙니다.

## 결과 폴더

예를 들어 `sample.seq`를 처리하면 다음 파일이 생깁니다.

```text
입력폴더/
  sample.seq
  result/
    sample_0.pdb                # confidence_score가 가장 높은 모델
    sample_1.pdb
    sample_2.pdb
    sample_3.pdb
    sample_4.pdb
    aligned/
      sample_0.pdb              # chain A 정렬 후 복합체 전체 좌표
      ... sample_4.pdb
    images/
      sample_aligned.png       # PyMOL 렌더링, 1200 × 850
      sample_aligned.pse       # PyMOL에서 다시 열 수 있는 세션
    evaluation/
      sample.csv               # 모델별 confidence / pLDDT / pTM / ipTM / RMSD
      sample.json              # 원래 FASTA 이름과 chain 매핑, 상세 신뢰도
      sample.manifest.json     # 입력 설정 및 출력 검증 정보
    logs/
      batch_날짜시간.log        # 전체 실시간 로그
      sample_날짜시간.log       # 해당 파일의 상세 로그
      summary_날짜시간.json     # 완료/실패/중지 집계
    history/                   # 기존 결과 교체 시 이전 파일 보관
    .msa_cache/                # 재사용 가능한 정렬
    .boltz_work/               # Boltz 원본 CIF, PAE/pLDDT NPZ, 중간 파일
```

모든 `.seq` 파일의 원본 PDB들은 같은 `result` 폴더에 모입니다.
이미지 생성에 실패해도 검증된 PDB 5개와 신뢰도 표는 저장하며, 상태에 이미지 실패를 표시합니다.

## 예측과 평가 방식

- Boltz 2.2.1 / Boltz-2, RTX 3060 CUDA, BF16 mixed precision.
- 파일별 5 samples, recycling 3, sampling steps 200, seed 42.
- 메모리 절약을 위해 동시 sample 1개. 파일마다 독립 프로세스로 실행해 GPU 메모리를 반환합니다.
- Windows에서 선택적 cuEquivariance 커널은 끄고 PyTorch CUDA를 사용합니다.
- MSA 생성은 **서열을 ColabFold 서버에 전송**합니다. 서로 다른 단백질이 여럿이면 paired와 unpaired 정렬을 함께 사용합니다. 같은 서열의 사본은 MSA를 공유합니다.
- MSA가 실패하면 해당 파일을 실패 처리합니다. 사용자 모르게 single-sequence 모드로 바꾸지 않습니다.
- GPU 메모리가 부족하면 로그에 오류를 남기고 다음 파일로 넘어갑니다. 복합체를 분할하거나 서열을 자르지 않습니다.

후보들은 Boltz `confidence_score` 내림차순으로 `_0`~`_4`에 대응합니다. 모델 0을 기준으로 나머지 모델의 **chain A 전체 Cα**를 PyMOL `align(cycles=0)`으로 중첩합니다. 이상치 제거를 하지 않으며, 같은 회전·이동을 해당 모델의 **다른 chain에도 함께 적용**합니다. 따라서 chain B 등의 상대 위치 차이가 이미지에 남습니다.

이미지 색상은 0 파랑, 1 주황, 2 초록, 3 자홍, 4 청록입니다.

- 평균 pLDDT: 0–100으로 표시. 국소 구조의 모델 신뢰도입니다.
- pTM / ipTM: 0–1. ipTM은 복합체에서만 표시합니다.
- A RMSD: 기준 모델 0에 대한 chain A 전체 Cα 좌표 RMSD, 단위 Å.
- 낮은 RMSD는 후보끼리 비슷하다는 뜻이며 실험적 정확성의 증거는 아닙니다. 유연한 말단이 전체 Cα RMSD를 크게 만들 수 있습니다.

## 재실행과 중지

기본적으로 입력/설정 fingerprint와 출력 파일 checksum이 모두 일치하면 완성된 결과를 재사용합니다.
이미지만 실패한 경우 검증된 Boltz 원본 결과를 재사용해 PyMOL 단계를 다시 시도합니다.
`완료된 결과도 다시 계산`을 켜면 별도 작업 폴더에서 다시 예측하고 이전 공개 결과는 history에 보관합니다.
`현재 작업 중지`는 실행 중인 모델링/PyMOL 하위 프로세스를 중지합니다. 완성된 결과는 보존합니다.
창을 닫을 때 작업이 실행 중이면 중지 완료 후 닫힙니다. 같은 입력 폴더에서 배치를 동시에 두 번 시작할 수 없습니다.

## 화면 없는 실행

```powershell
& 'D:\G박사\boltz_data\.venv\Scripts\python.exe' -u 'D:\G박사\boltz_data\boltz_batch_runner.py' --folder 'D:\내서열폴더'
```

## 검증 예제

`batch_examples/complex_demo.seq`는 기능 검증용 2-chain 예제입니다. 실제 Boltz GPU 실행으로 5개 모델을 생성하고 PyMOL 정렬/렌더링까지 검증했습니다. 지정된 disulfide 제약 등을 포함한 생물학적 해석용 설정은 아닙니다.

공식 참고: [Boltz prediction](https://github.com/jwohlwend/boltz/blob/main/docs/prediction.md), [PyMOL command reference](https://pymol.org/pymol-command-ref.html).
