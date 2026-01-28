Claim | Evidence | Strength | Flags
--- | --- | --- | ---
`/instruction/20260128_testRL.txt` 내용 기준으로 진행해야 하나, 현재 제공된 인스트럭션 파일은 **URL 2개만 있는 형태**로 보이며(실질적 “보고서 포커스 프롬프트” 부재), 따라서 이번 런의 핵심 포커스는 **arXiv 논문(2601.07145v1) 중심의 RL 기반 합성가능 형광체(fluorophore) 스캐폴드 생성**으로 간주해 소스 스카우팅/읽기 계획을 제안합니다. | (none) | none | no_evidence
포함 URL: arXiv PDF, LinkedIn 포스트(팬리 공유 링크) | (none) | none | no_evidence
`archive/arxiv/papers.jsonl` ✅ (존재, 1개 레코드: 2601.07145v1) | (none) | none | no_evidence
`archive/tavily_search.jsonl` ❌ | (none) | none | no_evidence
`archive/openalex/works.jsonl` ❌ | (none) | none | no_evidence
`archive/youtube/videos.jsonl` ❌ | (none) | none | no_evidence
`archive/local/manifest.jsonl` ❌ | (none) | none | no_evidence
-- | (none) | none | no_evidence
`archive/20260128_testRL_01-index.md` | (none) | none | no_evidence
이번 수집 결과 요약(다운로드/추출 목록) | (none) | none | no_evidence
`archive/_job.json` | (none) | none | no_evidence
실행 파라미터/잡 메타(재현성 확인용) | (none) | none | no_evidence
`archive/_log.txt` | (none) | none | no_evidence
수집 로그(에러/누락 확인용) | (none) | none | no_evidence
`archive/arxiv/papers.jsonl` | (none) | none | no_evidence
arXiv 메타(제목/초록/저자/발행일/링크) | (none) | none | no_evidence
`archive/arxiv/pdf/2601.07145v1.pdf` | (none) | none | no_evidence
원문 PDF | (none) | none | no_evidence
`archive/arxiv/text/2601.07145v1.txt` | (none) | none | no_evidence
PDF 텍스트 추출본(빠른 검색/인용 후보 파악용) | (none) | none | no_evidence
`archive/tavily_extract/0001_https_arxiv.org_pdf_2601.07145.txt` | (none) | none | no_evidence
arXiv PDF 페이지 추출(대체로 논문 텍스트와 중복 가능) | (none) | none | no_evidence
`archive/tavily_extract/0002_https_www.linkedin.com_posts_fanli_with-all-the-new-ai-tools-in-molecular-design-activity-7417558711084384256-ERGI_utm_s.txt` | (none) | none | no_evidence
LinkedIn 포스트 추출(맥락/요약/홍보성 코멘트 가능) | (none) | none | no_evidence
`report_notes/source_index.jsonl` | (none) | none | no_evidence
소스 인덱스(보고서 본문 인용용 아님) | (none) | none | no_evidence
`report_notes/source_triage.md` | (none) | none | no_evidence
현재는 arXiv 1개만 high-score로 트리아지됨 | (none) | none | no_evidence
가장 빠르게 전체 구조(Introduction/Methods/Results/Filtering/Experiments)를 훑고, 필요한 섹션을 표적 읽기하기 좋음. | (none) | none | no_evidence
도표(Figure 1 파이프라인, 모델 성능표, 생성/필터링 플로우, 실험결과 구조식) 확인이 핵심. 텍스트 추출본에서 누락된 캡션/수식/표를 보완. | (none) | none | no_evidence
초록/메타데이터(발행일, 저자, 카테고리) 확인 및 서지 정리. (특히 초록에 핵심 성과: 11,590 생성 → 19 선정 → 14 합성 → 13 확인) | (none) | none | no_evidence
arXiv 텍스트와 중복 가능하지만, 추출 품질 차이로 인해 **문단/캡션 일부가 더 잘 잡혔는지** 빠르게 비교 확인. | (none) | none | no_evidence
외부 커뮤니케이션 관점의 요약/키 메시지(“왜 중요한가”, “어떤 툴 조합인가”)를 짧게 파악. 기술 검증보단 맥락용. | (none) | none | no_evidence
이번 런이 **URL 2개만** 담고 있어 커버리지가 매우 제한적임을 확정. 이후 추가 수집 필요성 판단에 사용. | (none) | none | no_evidence
openalex 옵션이 있었는데도 결과가 없는 이유(쿼리 0 등) 점검. 재런 시 쿼리/키워드 보강에 도움. | (none) | none | no_evidence
수집 실패/스킵 사유(네트워크, 파싱 오류, rate limit 등) 확인. | (none) | none | no_evidence
현재 트리아지 기준/스코어링이 단일 소스에 과도하게 의존하는지 확인(추가 소스 확장 필요 근거). | (none) | none | no_evidence
소스 ID/경로가 보고서 파이프라인에서 어떻게 참조되는지 확인(정리 작업 시 실수 방지). | (none) | none | no_evidence
**1단계(30–45분):** `arxiv/text`로 전체 훑기 → 아래 체크리스트에 따라 표시 | (none) | none | no_evidence
RL 환경/상태-행동 정의(빌딩블록/리액션 기반 생성 과정) | (none) | none | no_evidence
스코어링 함수 구성(PLQY 분류 + 흡수/방출 파장 회귀 + π-conjugation) | (none) | none | no_evidence
데이터(ChemFluor, solvent feature 포함 여부, 모델 성능지표) | (none) | none | no_evidence
필터링/선정 규칙(가시광 420–770nm, novelty/diversity 등) | (none) | none | no_evidence
실험 검증(합성 성공률, 확인된 13개, 상위 3개 특성치) | (none) | none | no_evidence
**2단계(30분):** `arxiv/pdf`로 그림/표/보충자료 관련 언급 확인 | (none) | none | no_evidence
Figure 1 파이프라인, Figure 2 모델 성능/데이터 분포 등 | (none) | none | no_evidence
**3단계(10분):** Tavily extract & LinkedIn은 “요약/맥락”만 확인하고 기술 근거는 논문에 고정 | (none) | none | no_evidence
**4단계(10분):** `_job.json`, `_log.txt`로 “왜 소스가 1편뿐인지” 점검 → 필요 시 재수집 전략 수립 | (none) | none | no_evidence
OpenAlex/추가 arXiv/리뷰/후속 블로그/코드 저장소(GitHub) 등이 **전혀 포함되지 않음**. | (none) | none | no_evidence
논문 내에서 언급되는 선행(예: SyntheMol-RL, ChemFluor dataset, Enamine REAL space 등)에 대한 **원 출처 파일이 아카이브에 없음**. | (none) | none | no_evidence