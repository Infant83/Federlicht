요약: 요청하신 쿼리(20260127_arxiv-molgenRL)에 대해 아카이브를 검토해 핵심 소스 파일을 식별했고(메타데이터 JSONL 파일들도 확인함) 우선 읽기 목록과 읽기 계획을 제안합니다. 포커스는 arXiv 논문 "Generating readily synthesizable small molecule fluorophore scaffolds with reinforcement learning" (SyntheFluor‑RL)이며, 포커스 관련 자료만 우선으로 포함하고 오프토픽 항목은 제외했습니다.

1) 구조화된 인벤토리 — 핵심 소스와 지원 산출물
- 핵심 원문 (primary)
  - ./archive/arxiv/pdf/2601.07145v1.pdf
    - 원본 PDF. 그림·보조자료와 포맷 보존 필요 시 우선 열람.
  - ./archive/arxiv/text/2601.07145v1.txt
    - PDF에서 추출한 텍스트(검색·빠른 스캔에 유리). 본문 전체가 포함되어 있음.
  - ./archive/tavily_extract/0001_https_arxiv.org_pdf_2601.07145.txt
    - 웹 추출(다른 추출본). 빠른 요약/본문 부분 복수 확인용.
- 메타데이터 · 인덱스 (참조용, 항상 열람 권장)
  - ./archive/arxiv/papers.jsonl
    - arXiv 메타데이터(제목, 저자, 요약, pdf_url 등). 전체 아카이브 커버리지를 확인하는 데 사용.
  - ./report_notes/source_index.jsonl
    - 보고서용 소스 인덱스(이 쿼리와 매칭된 소스 항목).
  - ./report_notes/source_triage.md
    - 경량 소스 트리아지(우선순위·점수 메모).
  - ./archive/20260127_arxiv-molgenRL-index.md
    - 실행(run) 인덱스: 어떤 파일들이 수집됐는지 요약.
- 부수/로깅 파일 (낮은 우선순위)
  - ./archive/_job.json, ./archive/_log.txt
    - 수집/실행 로그(문제가 발생했을 때 확인).
- 제외(오프토픽)
  - ./archive/tavily_extract/0002_https_www.linkedin...txt
    - LinkedIn 공유글 추출 — 본 쿼리(논문 중심)와 직접 관련 적음으로 제외.

참고: 요청 지침에 따라 존재하는 메타데이터 JSONL 열람은 수행했습니다(예: archive/arxiv/papers.jsonl, report_notes/source_index.jsonl). JSONL의 구체 본문을 보고서 본문으로 인용하지는 않습니다.

2) 우선 읽기 목록(최대 12개) — 순서, 이유, 권장 읽기 포커스
(각 항목에 대해 권장 읽기 시간은 대략치입니다)

1. ./archive/tavily_extract/0001_https_arxiv.org_pdf_2601.07145.txt — 10–15 min (빠른 스캐닝)
   - 이유: 논문 전체 텍스트의 추출본으로 검색·스킴에 가장 빠름. 주요 주장, 숫자(생성 숫자 11,590 → 19 → 14→13/3개 최종 특성화)와 전반적 흐름 파악이 목적.
   - 포커스: Abstract, Results 개요(생성·필터링·실험 검증), 주요 수치(rollouts, 생성 수, 합성 성공률), 결론 요지.

2. ./archive/arxiv/text/2601.07145v1.txt — 15–25 min (정밀한 본문 검토)
   - 이유: PDF와 동일 내용의 텍스트형식. 그림 캡션·메서드 섹션까지 텍스트로 검색 가능.
   - 포커스: 2.2 Generating Molecules with SyntheFluor‑RL(알고리즘 설명), 2.1(모델 학습/데이터: ChemFluor), 2.3(실험적 특성화: Compound 13 등), Filtering 단계(필터링 기준 및 순서).

3. ./archive/arxiv/pdf/2601.07145v1.pdf — 45–75 min (정밀, 도표·보조자료 확인)
   - 이유: 그림, 서플리먼터리 표, 정확한 형식·수식·그래픽 정보를 확인해야 함. 반응 목록(추가된 57 reactions)과 Figure S1–S3 등 시각적 결과 확인 필수.
   - 포커스: Figure 1–5 및 Supplementary Figures(특히 reaction ID 분포, dynamic weighting plot), Methods(4.2–4.6): SyntheFluor‑RL 아키텍처, value/reward 함수, dynamic weighting, sp2 network algorithm, TD‑DFT 필터링 파라미터, 합성(Enamine) 관련 절차.

4. ./archive/arxiv/papers.jsonl — 5 min (메타데이터 검증)
   - 이유: 출처·발표일·저자·초록의 빠른 확인 및 인용 메타데이터 확보.
   - 포커스: published/updated 날짜, primary_category, summary(초록) 재확인.

5. ./report_notes/source_index.jsonl — 2–5 min (보고용 출처 매핑)
   - 이유: 보고서 생성 시 소스 경로/파일 경계를 맞추기 위함(텍스트/ pdf 경로 확인).
   - 포커스: text_path, pdf_path, id 필드 확인.

6. ./report_notes/source_triage.md — 2 min (트리아지 확인)
   - 이유: 소스 평가(점수·우선순위) 근거를 확인해 추가 자료 필요 여부 판단.
   - 포커스: 트리아지 코멘트(이 논문이 우선 소스임을 재확인).

7. ./archive/20260127_arxiv-molgenRL-index.md — 5–10 min (수집 로그 및 관련 파일 목록 확인)
   - 이유: 수집 과정(다운로드된 파일, tavily_extract 항목 등)과 누락 여부 확인.
   - 포커스: tavily_extract 목록, PDF 존재 여부, 실행 커맨드.

8. ./archive/_log.txt, ./archive/_job.json — 필요 시(문제 재현·메타데이터 추적) — 5–15 min (선택)
   - 이유: 수집 과정에서 오류가 있었는지, 실행 파라미터가 어떻게 설정됐는지 확인해야 할 경우 열람.

(총 항목: 8 — 포커스는 전부 SyntheFluor‑RL 논문 및 관련 인덱스/추출본으로 구성. off-topic LinkedIn 추출은 의도적으로 제외.)

3) 권장 읽기 계획(단계별)
- 1단계 (빠른 스캔, 20–30분)
  1) tavily_extract/0001 추출본 스캔 — 전체 구조·핵심 결과 파악.
  2) papers.jsonl · source_index.jsonl · source_triage.md 빠르게 확인(메타·우선순위 확인).

- 2단계 (본문 정밀 읽기, 45–90분)
  1) arxiv text 전체 정독: Introduction → Results(2.2, 2.3) → Figure 캡션(텍스트 내 캡션) → Discussion.
  2) arxiv PDF에서 도표·Supplementary figure 직접 확인: reaction 목록(확장된 57 reactions), Figure S1(반응 빈도), dynamic weighting plot.

- 3단계 (기술적 검증 · 재현성 점검, 60–120분)
  1) Methods(4.2–4.6) 집중: Chemprop‑Morgan/MLP‑Morgan 모델 구성, 데이터셋(ChemFluor) 처리, sp2 algorithm(구현 아이디어), RL value/reward 구성, dynamic weighting 및 temperature 목표(λ* = 0.6), TD‑DFT 필터링(함수/기초셋: B3LYP/3-21G*, SCRF water) 세부 파라미터.
  2) Data/code availability 문단에서 Zenodo/GitHub 링크(https://doi.org/10.5281/zenodo.18203970, https://github.com/swansonk14/SyntheMol) 확인 → 필요 시 코드/데이터 확보.

- 4단계 (실험 결과·응용 평가, 30–60분)
  1) 2.3 및 Supplementary: 합성 성공률(34→14→13), Compound 13 photophysics(PLQY=0.62, lifetime=11.55 ns, Stokes shift 97 nm), molar extinction coefficient 등 수치 검증.
  2) 실험 조건(용매, 농도, 측정 장비)과 세부 방법(quantum yield 계산 방법, lifetime 측정 장비/설정) 비교.

- 5단계 (후속 조사·확장)
  1) 코드와 데이터 내려받아 재생산(생성 파라미터·reaction set) 가능성 평가.
  2) 관련 문헌(참조: SyntheMol‑RL, ChemFluor, FLAME, DNMG 등)을 필요에 따라 추가 수집.

4) 선정 이유 요약 (우선순위 판단 근거)
- tavily_extract(0001)와 arxiv/text는 빠른 스캔·검색에 용이하므로 우선.
- arXiv PDF는 그림, 보조자료, 정확한 수치·서플리먼트가 포함되어 있어 깊이 읽을 때 필수.
- 메타데이터·인덱스 파일들은 출처 검증·보고서 작성용 참조로 필요.
- LinkedIn 추출 등 오프토픽 자료는 본 과제(논문 독해·재현성 평가)에 직접적 기여가 작아 제외.

5) 다음 권장 액션(제가 진행 가능)
- 원하시면 제가 제안한 우선순위 순서대로 실제 파일(예: arxiv text → arxiv PDF Methods 섹션 등)을 열어 세부 요약(핵심 문장 발췌, 재현성 체크리스트, 구현/실험 파라미터 표준화 권고)을 만들어 드릴 수 있습니다.
  - 빠른 요약(15–30분): 핵심 결과·수치와 재현성 위험 요소 정리.
  - 상세 기술 리뷰(1–2시간): Methods 재현성 점검(모델 하이퍼파라미터, reaction list, TD‑DFT 설정), 코드/데이터 확보 체크리스트.
- 어느 단계로 진행할지 알려주시면 해당 작업을 바로 시작하겠습니다.

작업 상태: 아카이브 조사 · 핵심 파일 식별 완료. 우선 읽기 목록 및 읽기 계획 제안 완료. 다음 단계(요약·심층검토 등)를 지시해 주세요.