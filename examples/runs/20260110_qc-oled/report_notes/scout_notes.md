아카이브 커버리지부터 보면, **“지난 12개월의 양자컴퓨팅 기반 재료연구/OLED 발광재료 적용”**이라는 포커스에 비해 현재 수집본은 **(1) QC-재료 일반 리뷰 1편**과 **(2) OLED/QC 직접 교차점은 주로 웹 검색(tavily) 결과(IBM 블로그, OLED-info 등)**에 크게 의존하는 구조입니다. **학술 논문(특히 QC for molecular excited states / OLED emitter design)**은 거의 비어 있어, 보고서 작성 시 “근거 강도: 높음”으로 쓸 수 있는 1차 문헌 풀이 부족합니다(추가 수집 필요 가능성 높음).

아래는 **파일 인벤토리(구조/내용/관련성)**와 **우선 읽기 계획(최대 12개)**입니다. (요청대로 한국어 메모, 고유명사/제목은 원문 유지)

---

## 1) 아카이브 맵(구조 인벤토리)

### A. 런/지시·인덱스(메타)
- `./instruction/20260110_qc-oled.txt`  
  - 검색 의도/키워드 중심. *산업체(삼성디스플레이, LG디스플레이, UDC) + “quantum computing materials discovery OLED”* 위주.
- `./archive/20260110_qc-oled-index.md`  
  - 이번 런 결과 요약: **Queries 9, URLs 0, arXiv 0**, OpenAlex OA 5(실제는 works.jsonl에 더 있음), PDF 7.
- `./archive/_job.json`, `./archive/_log.txt`  
  - 수집 파이프라인 로그/설정 확인용(누락 원인 추적에 유용).

### B. OpenAlex(논문) — 텍스트/PDF 있음(7개)
- `./archive/openalex/works.jsonl`  
  - OpenAlex 결과 원장(전체 목록/메타; 현재 OLED-QC 직접 논문이 거의 없음).
- PDF+추출텍스트 세트(각각 `pdf/`와 `text/`):
  - **Exploring quantum materials and applications: a review** (W4406477905) — QC/양자재료 일반 리뷰
  - **Using GNN property predictors as molecule generators** (W4410193211) — 분자 생성/ML, QC 직접은 아님(워크플로 논의 보조 가능)
  - **Quantum-AI Synergy and the Framework for Assessing Quantum Advantage** (W4417018335) — QC advantage 프레임워크(산업 적용 평가 관점에 유용)
  - **Forecasting the future: From quantum chips to neuromorphic engineering and bio-integrated processors** (W4410446803) — 전망성 글(근거 약할 수 있음)
  - **Electrospinning vs Fluorescent Organic Nano-Dots...** (W4406330631) — 발광/나노 소재 리뷰(직접 OLED emitter/QC는 약함)
  - 나머지 2편(간암/건축 파사드)은 **명확히 오프토픽**.

### C. Tavily 웹 검색 인덱스(“supporting” 후보)
- `./archive/tavily_search.jsonl`  
  - 실질적으로 **OLED×Quantum** 교차점은 여기에 집중.
  - source_index에 노출된 핵심 URL(대표):
    - IBM Research 블로그: **Unlocking today's quantum computers for OLED applications**
    - OLED-info 기사들: Mitsubishi Chemical/Deloitte Tohmatsu/Classiq, “Researchers combine classical computing with quantum computing…”, “Transforming Materials Science Through Quantum Collaboration”
    - 기업 PR/기술 소개: Samsung Display QD-OLED 페이지, LG corp 릴리즈 등
    - Phys.org(보도자료 성격), Wikipedia(비권장)

### D. 보고서/노트(작성용)
- `./report_notes/source_index.jsonl`  
  - 이번 런에서 확보된 “출처 목록”의 단일 인덱스(논문/웹 혼합).
- `./report_notes/source_triage.md`  
  - 1차 선별 결과(현재 선별 자체가 오프토픽 논문 다수 포함).
- `./report.md`  
  - 베이스라인 보고서(현재는 “Risks & Gaps” 중심의 초안 조각; 근거 인용 체계 미완).

---

## 2) 핵심 커버리지 진단(포커스 대비)

### 잘 있는 것
- **QC 일반/양자 advantage 논의(평가 프레임)**: (W4417018335 등) → “산업 적용의 한계/병목/QA(quantum advantage) 주장 검증” 섹션에 유용.
- **웹 기반 사례 단서**: IBM blog, OLED-info 등 → “산업계 시도와 공개정보 한계”를 서술할 때 단서 제공.

### 부족한 것(보고서 리스크)
- **OLED 발광재료(형광/인광/TADF/CP-OLED) 탐색에 QC가 실제로 쓰인 1차 논문/리뷰**가 아카이브에 사실상 없음.  
  - 특히 필요한 축: *excited states (S1/T1), SOC, ISC/RISC, ΔEST, oscillator strength, nonadiabatic coupling* 등 OLED 핵심 물성 예측에 QC가 어떤 방식으로 들어갔는지(예: VQE/UCC, QPE, quantum embedding, quantum ML 등).
- 산업체(삼성디스플레이/LG디스플레이/UDC)의 **QC 활용 공개자료**는 이번 수집본에서 대부분 “QD(quantum dot)” 관련 페이지로 흐르며, **quantum computing과 혼동**될 가능성 큼(용어 충돌).

---

## 3) 우선 읽기 계획 (Top 12) + 읽는 이유

> 목표: “(1) QC 기반 재료탐색 워크플로/알고리즘” 골격을 세우고, “(2) OLED 적용 주장”은 supporting으로 격리, “(3) 산업 적용 간극/병목”을 근거 기반으로 정리.

1) `./archive/tavily_search.jsonl`  
- 이유: OLED×Quantum 관련 단서가 여기 집중. 어떤 웹 문서가 “공식 발표/기업 블로그/업계 매체”인지 분류해야 함.  
- 산출: supporting 소스 후보 목록, 신뢰도(공식/2차/3차) 라벨링.

2) `./archive/openalex/text/W4417018335.txt` — *Quantum-AI Synergy and the Framework for Assessing Quantum Advantage*  
- 이유: “양자 이점 주장 평가 프레임”은 산업 적용 간극/병목을 논문형 서술로 정리하는 데 직접 필요.

3) `./archive/openalex/text/W4406477905.txt` — *Exploring quantum materials and applications: a review*  
- 이유: QC/양자재료 분야의 큰 흐름(응용 범주, 재료/디바이스 영역)을 개괄로 인용 가능. (다만 OLED-specific은 약할 것)

4) `./archive/openalex/text/W4410193211.txt` — *Using GNN property predictors as molecule generators*  
- 이유: “재료 탐색 워크플로(생성모델+property predictor+active learning)”를 설명할 때, QC가 아직 약한 구간을 보완하는 **비교 기준(고전적 SoTA)** 으로 활용 가능.

5) `./archive/openalex/text/W4410446803.txt` — *Forecasting the future: From quantum chips to neuromorphic…*  
- 이유: 12~24개월 전망 파트에서 참고 가능(단, 근거 강도는 낮게 취급).

6) `./archive/openalex/text/W4406330631.txt` — *Electrospinning vs Fluorescent Organic Nano-Dots…*  
- 이유: 발광 소재(organoluminophores) 주변부 배경용. OLED emitter 중심성과는 거리 있으나 “발광 소재 카테고리/나노-광물성” 참고.

7) `./archive/openalex/works.jsonl`  
- 이유: OpenAlex 수집의 스코프 점검(왜 OLED/QC 핵심 논문이 빠졌는지) 및 추가 수집 전략 수립 근거.

8) `./archive/20260110_qc-oled-index.md`  
- 이유: 수집 범위/성공 여부(Queries 9, URLs 0, arXiv 0) 확인 → “왜 학술 1차 문헌이 빈약한지” 점검.

9) `./archive/_log.txt`  
- 이유: 수집 실패/필터링/다운로드 이슈 여부 확인(추가 실행 시 수정 포인트).

10) `./report_notes/source_index.jsonl`  
- 이유: 현재 인용 후보들의 전체 목록을 보고 “논문 vs supporting” 구분 체계 설계.

11) `./report_notes/source_triage.md`  
- 이유: 기존 triage가 오프토픽을 다수 포함하므로, **재-triage**의 출발점.

12) `./report.md`  
- 이유: 기존 초안의 논리 구조/갭(근거-한계-해석 포맷 미충족)을 파악해, 이후 재작성 시 최소 변경/최대 개선 지점 식별.

---

## 4) 다음 액션 제안(아카이브 밖이지만, “소스 스카우트” 관점의 권고)

- **추가 수집(강력 권고)**: 지난 12개월 범위에서
  - “quantum computing” AND (OLED OR “organic light-emitting” OR TADF OR “phosphorescent emitter” OR “excited state”)  
  - “VQE” AND (excited states OR “EOM” OR “linear response”) AND (organic molecules)  
  - “quantum algorithms” AND “computational chemistry” AND “materials discovery”  
  같은 조합으로 **arXiv/ACS/APS/Nature portfolio의 1차 문헌**을 보강하지 않으면, OLED 관점의 “근거 강도: 높음” 주장 구성에 구조적 한계가 큼.

원하면 제가 다음 단계로, `tavily_search.jsonl`을 실제로 열어 **OLED×QC 관련 URL을 ‘공식/논문/업계/블로그’로 재분류한 소스 맵**(supporting 라벨 포함)도 만들어 드릴 수 있습니다.