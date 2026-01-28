아래는 제공된 아카이브를 검토(메타데이터 확인 포함)해 선별한 소스 목록과, 해당 문서들에서 직접 추출한 핵심 사실들입니다. 소스는 유형별로 묶었고(고유명사·제목은 원문 언어 유지), 가능한 경우 원문 URL과 로컬에 저장된 추출본/PDF 파일 경로를 함께 표기했습니다.

소스 인벤토리 (유형별)
- Primary (논문 원문)
  - "Generating readily synthesizable small molecule fluorophore scaffolds with reinforcement learning" (arXiv:2601.07145v1) — 원문 PDF 및 텍스트 추출본  
    - PDF: [/archive/arxiv/pdf/2601.07145v1.pdf] (원문 URL: https://arxiv.org/pdf/2601.07145)  
    - 텍스트 추출본: [/archive/arxiv/text/2601.07145v1.txt]  
    - 추가 웹 추출(복수 추출본): [/archive/tavily_extract/0001_https_arxiv.org_pdf_2601.07145.txt] (contains full extracted raw content)
- Metadata / index (참조용)
  - arXiv 메타데이터 레코드: [/archive/arxiv/papers.jsonl] (사용해 커버리지 확인함; 인용은 원문으로)  
  - 수집/보고용 인덱스·트리아지: [/archive/20260127_arxiv-molgenRL-index.md], [/report_notes/source_index.jsonl], [/report_notes/source_triage.md]
- Code / data availability (언급된 외부 리포지터리)
  - Zenodo (data): https://doi.org/10.5281/zenodo.18203970  
  - GitHub (code): https://github.com/swansonk14/SyntheMol

핵심 사실 (근거와 함께; 각 항목 뒤에 출처 표기)
- 논문·식별
  - 제목: "Generating readily synthesizable small molecule fluorophore scaffolds with reinforcement learning" (arXiv:2601.07145v1, posted 12 Jan 2026). [PDF: /archive/arxiv/pdf/2601.07145v1.pdf; text: /archive/arxiv/text/2601.07145v1.txt; arXiv: https://arxiv.org/abs/2601.07145]

- 데이터셋 및 모델
  - 학습 데이터: ChemFluor dataset — 2,912 고유 분자, 63 용매 → 4,336 molecule–solvent pairs (PLQY / absorption / emission 데이터 포함). [text: /archive/arxiv/text/2601.07145v1.txt]
  - Property predictor 아키텍처: Chemprop-Morgan (GNN + Morgan fingerprints)와 MLP-Morgan 사용. Morgan fingerprint 기반이 RDKit 기반보다 성능 우수. [text: /archive/arxiv/text/2601.07145v1.txt]
  - PLQY 분류 성능(보고된 예): Chemprop‑Morgan ROC‑AUC = 0.895 ± 0.019. Absorption MAE ≈ 13.12 ± 1.20 nm; Emission MAE ≈ 18.95 ± 0.99 nm. [text: /archive/arxiv/text/2601.07145v1.txt]

- 생성(Generation) 및 반응 집합
  - SyntheFluor‑RL이 생성한 후보 수: 11,590 molecules (생성 과정: 10,000 rollouts). [text: /archive/arxiv/text/2601.07145v1.txt; PDF: /archive/arxiv/pdf/2601.07145v1.pdf]
  - 반응 세트: 원래 SyntheMol‑RL의 13 reaction pathways에 추가로 Enamine REAL에서 57 reactions를 더해 총 70 reactions 사용(그중 실제로는 18 unique reactions가 쓰였고, 새로 추가된 반응에서 5개가 사용됨). [text: /archive/arxiv/text/2601.07145v1.txt; PDF]
  - 계산 리소스 및 시간: 10,000 rollouts 실행에 16시간 38분 26초 소요(보고된 환경: 32 CPUs 및 1 GPU). [text: /archive/arxiv/text/2601.07145v1.txt]

- 스코어링·보상·동적조정
  - 최적화 목적: 네 가지 속성 동시 최적화 — PLQY (p(PLQY>0.5)), absorption wavelength, emission wavelength, sp2 network size. [text: /archive/arxiv/text/2601.07145v1.txt]
  - sp2 네트워크: 분자의 최대 연결 sp2 원자 네트워크 크기를 계산하는 알고리즘(DFS 기반)을 도입. sp2 network size ≥ 12를 성공 임계값으로 사용. [text: /archive/arxiv/text/2601.07145v1.txt]
  - 동적 가중치 및 온도 조정: 롤아웃 기반 rolling success rates에 따라 property weights와 RL temperature를 동적으로 조정. 목표 Tanimoto 유사도 λ* = 0.6 (평균 유사도 목표). [text: /archive/arxiv/text/2601.07145v1.txt]

- 필터링·후보 선별 파이프라인 (숫자 흐름)
  - 11,590 → sp2 size <12 필터로 5,479 제거 → PLQY filter(p>0.5)로 4,256 제거 → absorption/emission (visible 420–750 nm) 필터로 각각 21 및 1,203 제거 → 남은 631 molecules. [text: /archive/arxiv/text/2601.07145v1.txt]
  - 다양성 유지: Morgan fingerprint 기반 Tanimoto similarity로 K‑means clustering(100 clusters) → cluster당 1개 수동 선택 → 52 후보 → Enamine에서 34가 합성 가능(available)으로 확인. [text: /archive/arxiv/text/2601.07145v1.txt]
  - TD‑DFT(최종 계산) 필터: B3LYP/3‑21G* (geometry opt), SCRF water 모델, TD‑DFT로 첫 5 singlet 상태 계산; oscillator strength > 0.01 임계값 → 34 → 19 최종 후보로 축소. [text: /archive/arxiv/text/2601.07145v1.txt]

- 합성 및 실험 검증
  - 합성 요청/결과: 19 후보 중 14 compounds가 Enamine에서 합성(합성 의뢰), 그중 1개는 수령 시 분해(decomposed)되어 최종 실험 대상 13 compounds. [text: /archive/arxiv/text/2601.07145v1.txt]
  - 실험 결과(개요): 13 tested → 상위 3개(Compounds 13, 2, 11)가 가장 밝음. Compound 13이 가장 우수. [text: /archive/arxiv/text/2601.07145v1.txt; PDF]
  - Compound 13 주요 광물리 수치(실험값):
    - Photoluminescence quantum yield (PLQY) = 0.62 (quinine standard 비교법),  
    - Fluorescence lifetime (amplitude-weighted mean τ) = 11.55 ns,  
    - Stokes shift = 97 nm,  
    - Molar extinction coefficient ε ≈ 6,000 M−1·cm−1.  
    - 측정 용매/조건: chloroform 10 mM 용액, Fluorolog 3 spectrofluorometer, TCSPC (nanoLED405) 사용 등. [text: /archive/arxiv/text/2601.07145v1.txt; PDF]
  - 생체적용성(간단 평가): HEK293 live‑cell imaging에서 Compound 13은 세포투과성·dose‑dependent fluorescence 보임(0.1, 1, 10 µM); mean pixel intensity 값 표기(0.020 → 0.121 → 0.140). [text: /archive/arxiv/text/2601.07145v1.txt]

- 방법론·재현성 관련 세부사항(중요 파라미터)
  - PLQY 모델링: PLQY는 이진 분류로 취급(PLQY > 0.5 기준). Absorption/emission은 회귀 모델. 10‑fold CV 사용(80/10/10 split). Chemprop v1.6.1 사용. [text: /archive/arxiv/text/2601.07145v1.txt]
  - TD‑DFT 상세: Gaussian, B3LYP/3‑21G*, MMFF 초기 구조, SCRF water, 최대 최적화 사이클 1000, 첫 5 singlet states 계산. Oscillator strength cutoff = 0.01. [text: /archive/arxiv/text/2601.07145v1.txt]
  - Value function: MLP‑Morgan 모델(빠른 평가)로 intermediate scoring, 최종 후보 평가는 Chemprop‑Morgan (정밀)으로 수행하는 하이브리드 워크플로우. [text: /archive/arxiv/text/2601.07145v1.txt]

- 성과·비교 관찰
  - 생성물 분포: SyntheFluor‑RL이 생성한 분자들은 무작위 Enamine REAL 샘플보다 p(PLQY>0.5) 확률과 sp2 네트워크 크기에서 유의하게 우수한 분포를 보였음(즉, fluorescence‑like 성질로 enrichment됨). [text: /archive/arxiv/text/2601.07145v1.txt; PDF]
  - 계산비용 비교: 보고서에선 SyntheFluor‑RL이 10,000 rollouts를 16.5시간에 생성(32 CPU + 1 GPU)한 반면, 다른 접근(DNMG)은 더 많은 CPU와 긴 시간이 필요했음을 언급(비교 목적). [text: /archive/arxiv/text/2601.07145v1.txt]

- 재현 가능성 / 리소스 링크
  - 데이터 및 코드 공개: Zenodo DOI(https://doi.org/10.5281/zenodo.18203970) 및 GitHub(https://github.com/swansonk14/SyntheMol)에서 학습 데이터·모델·generation inputs·generated molecules·코드 제공(논문 본문에서 명시). [text: /archive/arxiv/text/2601.07145v1.txt]

참고 및 제안된 다음 단계
- 제가 우선적으로 확보·검토한 로컬 파일: [/archive/tavily_extract/0001_https_arxiv.org_pdf_2601.07145.txt] (빠른 검색·발췌용), [/archive/arxiv/text/2601.07145v1.txt] (정밀 텍스트), [/archive/arxiv/pdf/2601.07145v1.pdf] (도표·supplement 확인용). 원하시면 이들 파일을 근거로
  - (A) 간략 요약(핵심 수치·재현성 리스크) — 15–30분 작업  
  - (B) 상세 기술 리뷰(Methods 섹션에서 재현성 체크리스트, 필요한 코드·데이터 다운로드 지침 포함) — 1–2시간 작업  
  중 어느 것을 수행할지 알려주세요. 원하시면 Compound 13의 실험 파라미터(예: quantum yield 계산 값, lifetime fitting 파라미터 등)를 PDF에서 캡처해 더 세부적으로 근거 추출해 드립니다.

원문·로컬 파일로 근거를 확보해 요약·검토해 드릴 수 있습니다. 어떤 후속 작업을 진행할지 지시해 주세요.