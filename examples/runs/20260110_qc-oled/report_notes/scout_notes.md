## 1) 아카이브 맵(coverage/갭 진단)

### A. 필수 인덱스/메타데이터(“지도” 역할)
- `./archive/20260110_qc-oled-index.md`  
  - 수집 개요: 지난 365일, Tavily 쿼리 9, OpenAlex 5(텍스트/ PDF 7개 다운로드), arXiv 0.
- `./instruction/20260110_qc-oled.txt`  
  - 쿼리 의도: “quantum computing materials discovery OLED …”, 기업(Samsung Display/LG Display/UDC) 키워드 중심.
- `./report_notes/source_index.jsonl`  
  - 실제로 활용 가능한 소스 목록(=논문 OA + 웹 결과). IBM Research 블로그(quantum-for-oled) 등 핵심 URL 포함.
- `./archive/openalex/works.jsonl`  
  - OpenAlex로 들어온 논문 메타데이터 원장. (OLED/양자계산 직접 관련은 빈약)
- `./archive/tavily_search.jsonl`  
  - 웹 검색 결과 원장. OLED×quantum 관련 실마리 다수(IBM Research, OLED-Info 등). 단, “supporting” 성격이 강한 항목이 섞여 있음.

### B. 1차 문헌(논문/리뷰) — OpenAlex 텍스트+PDF 존재(검증용)
- `./archive/openalex/text/W4406477905.txt` (+pdf) — *Exploring quantum materials and applications: a review*  
  - “양자재료(quantum materials)” 리뷰로, **양자컴퓨팅 기반 재료 탐색**과는 다른 결의 가능성(용어 혼재 주의).
- `./archive/openalex/text/W4410193211.txt` (+pdf) — *Using GNN property predictors as molecule generators* (Nature Communications 2025)  
  - 양자컴퓨팅은 아니지만, **재료/분자 생성·예측 워크플로(ML 파이프라인)** 비교 기준으로 유용.
- `./archive/openalex/text/W4417018335.txt` (+pdf) — *Quantum-AI Synergy and the Framework for Assessing Quantum Advantage*  
  - “quantum advantage” 주장 평가 프레임워크로, **산업 적용의 근거 강도/불확실성 평가**에 직접 도움.
- `./archive/openalex/text/W4406330631.txt` (+pdf) — *Electrospinning vs Fluorescent Organic Nano-Dots…*  
  - OLED 발광재료 핵심과는 거리가 있음(organoluminophores 일반). 우선순위 낮음.
- `./archive/openalex/text/W4410446803.txt` (+pdf) — *Forecasting the future: From quantum chips…*  
  - 전망/에세이 성격 가능. 근거 강도 낮을 수 있어 보조적.

※ 소스 트리아지에 있는 간암/건축 파사드/센서/이미징 등은 **보고서 초점(OLED 발광재료×양자컴퓨팅)** 관점에서 대부분 오프토픽.

### C. 웹(supporting) — 산업/협업 힌트가 많음(단, 1차 문헌으로 격상 필요)
`./archive/tavily_search.jsonl` 내 핵심 후보(제목 기준):
- IBM Research blog: *Unlocking today's quantum computers for OLED applications* (arXiv 프리프린트 언급)
- mcgc.com PDF: *A Joint Paper on Prediction of Optical Properties of OLED Materials …* (npj Computational Materials 언급)
- OLED-Info 기사들: Mitsubishi Chemical / Classiq / Deloitte Tohmatsu 관련, “circuit compression”, “QAOA” 등의 키워드
- 기업 PR/기술 소개: `samsungdisplay.com ... quantum-dot.jsp`, LG Corp release, UDC IR press releases 등  
  - 다만 이것들은 **OLED 소재 R&D에 양자컴퓨팅을 실제 적용**했다는 직접 근거가 아닐 가능성이 큼(공개 정보 한계 파트에 활용).

### D. 커버리지 갭(중요)
- **arXiv/학술 1차 문헌이 아카이브에 직접 포함되어 있지 않음**: IBM 블로그가 언급한 arXiv 프리프린트/npj Computational Materials 논문이 핵심인데, 현재 폴더에는 해당 논문 PDF/텍스트가 “1차 문헌”으로 들어와 있지 않음(웹 링크/요약만 존재).  
- OpenAlex 결과는 **OLED×quantum computing 직접 타격 문헌이 거의 없음**. 즉, 현 아카이브만으로는 “지난 12개월” 동향을 엄밀히 쓰기엔 근거가 약해질 위험이 큼. (보고서 작성 전, 해당 핵심 논문을 추가 수집하는 것이 바람직)

---

## 2) 핵심 소스 파일 인벤토리(구조화)

### (1) 인덱스/로그
- `archive/20260110_qc-oled-index.md` — 수집 범위/파일 링크 요약
- `archive/_job.json`, `archive/_log.txt` — 수집 설정/실패 여부 확인용

### (2) OpenAlex 메타데이터/원문
- `archive/openalex/works.jsonl` — OA 결과 메타데이터(쿼리별)
- `archive/openalex/text/*.txt` — 추출 텍스트(7개)
- `archive/openalex/pdf/*.pdf` — 원문 PDF(7개)

### (3) Tavily 웹 검색 원장(supporting)
- `archive/tavily_search.jsonl` — 쿼리별 결과/요약 포함(산업 협업 실마리)

### (4) 리포트 노트
- `report_notes/source_index.jsonl` — 실제 인용 후보(논문/웹) 통합 인덱스
- `report_notes/source_triage.md` — 1차 선별(다수 오프토픽 포함)

---

## 3) 우선 읽기 플랜(최대 12개) + 선정 근거
아래는 “OLED 발광재료 개발 관점의 양자컴퓨팅 기반 재료 연구/산업 적용”에 **직접적으로 기여**하거나, 보고서의 “근거 강도·한계” 프레임을 세우는 데 중요한 순서입니다.

1. `./archive/tavily_search.jsonl`  
   - **이유**: OLED×quantum computing 직접 언급(IBM Research, Mitsubishi Chemical 협업, QAOA/circuit compression, npj/arXiv 힌트)이 대부분 여기서 나옴.  
   - **용도**: 1차 문헌으로 끌고 갈 “표적 논문/발표/특허/기업자료” 후보를 추출.

2. `./report_notes/source_index.jsonl`  
   - **이유**: 실제 인용 후보를 한 번에 조망(웹/논문 혼재). 누락/중복/오프토픽 정리의 출발점.

3. `./archive/openalex/text/W4417018335.txt` (*Quantum-AI Synergy and the Framework for Assessing Quantum Advantage*)  
   - **이유**: “양자 우위/실용 우위” 주장에 대한 평가 틀은 산업 적용 간극·병목 분석에 핵심.  
   - **용도**: “근거 강도(높음/중간/낮음)” 판정 기준을 보고서에 내재화.

4. `./archive/openalex/text/W4410193211.txt` (*Using GNN property predictors as molecule generators*)  
   - **이유**: 실제 현업 워크플로는 “QC 단독”이 아니라 **QC+고전 계산+ML** 혼합이 많음. 생성모델/예측기 기반 파이프라인을 비교축으로 제공.  
   - **용도**: “양자컴퓨팅이 들어가면 어디가 바뀌는가?”를 구체화(데이터 파이프라인, surrogate model, active learning 등).

5. `./archive/openalex/text/W4406477905.txt` (*Exploring quantum materials and applications: a review*)  
   - **이유**: 제목은 유사하지만 주제가 “quantum materials”일 가능성이 높아 용어 혼선을 정리해야 함.  
   - **용도**: “양자컴퓨팅 기반 재료 탐색”과 “양자재료 연구”의 경계/차이를 서론에서 명확히.

6. `./archive/20260110_qc-oled-index.md`  
   - **이유**: 수집 범위가 “지난 12개월”로 설정됐으나 실제 결과가 그 목적을 충족하는지 점검 필요. (arXiv 0건 등)

7. `./instruction/20260110_qc-oled.txt`  
   - **이유**: 어떤 키워드가 빠졌는지(예: “VQE excited states”, “EOM-VQE”, “qEOM”, “error mitigation”, “TADF singlet-triplet gap”, “ΔEST”, “SOC”, “phosphorescent Ir complex” 등) 진단해 추가 수집 전략을 세움.

8. `./archive/openalex/text/W4410446803.txt` (*Forecasting the future…*)  
   - **이유**: 12–24개월 전망 파트에 보조 근거. 단, 전망/에세이이면 근거 강도 낮음 표기 필요.

9. `./archive/openalex/text/W4406330631.txt` (*Electrospinning vs Fluorescent Organic Nano-Dots…*)  
   - **이유**: OLED 발광재료 직접성은 낮지만, “발광 유기소재/나노구조화” 일반 논점이 필요할 때만 제한적으로 사용.

10. `./archive/_log.txt`  
   - **이유**: 수집 실패/차단/다운로드 누락 확인(특히 IBM 블로그가 언급한 arXiv/npj 논문이 왜 미포함인지 단서).

11. `./archive/openalex/works.jsonl`  
   - **이유**: OpenAlex가 어떤 쿼리에 어떤 결과를 반환했는지 확인하여 “학술 근거 부족”의 원인을 분석(쿼리 수정 포인트 도출).

12. `./report_notes/source_triage.md`  
   - **이유**: 현재 트리아지 목록이 오프토픽 비중이 커서, 무엇을 버려야 하는지(스코어링 오류)를 확인하는 용도.

---

## 4) 실행 관점 코멘트(보고서 품질 리스크)
- 현재 아카이브는 **“OLED 발광재료에 양자컴퓨팅을 실제 적용한 1차 연구(논문/프리프린트/공식 발표)”가 텍스트/PDF로 확보되어 있지 않아**, 보고서에서 “주장→근거(출처)”의 근거가 웹 요약에 치우칠 위험이 큼.  
- Tavily에 등장하는 다음 항목은 **반드시 1차 문헌으로 격상(원문 확보)해야** 보고서가 엄밀해짐:
  - IBM Research blog가 언급한 arXiv 프리프린트: *Applications of Quantum Computing for Investigations of Electronic Transitions in Phenylsulfonyl-carbazole TADF Emitters*  
  - mcgc.com PDF가 언급한 npj Computational Materials 논문(“excited states of TADF emitters”, “error mitigation”) 원문

원하시면, 다음 단계로 **tavily_search.jsonl에서 위 1차 문헌의 정확한 식별자(DOI/arXiv ID/저자/연도)만 뽑아내는 추가 스카우팅**(아카이브 내부 범위에서)도 바로 진행하겠습니다.