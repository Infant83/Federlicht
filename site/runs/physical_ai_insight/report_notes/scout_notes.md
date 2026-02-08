## 1) 아카이브 매핑(coverage) 요약 — Run ID: physical_ai_insight

### 필수 인덱스(JSONL) 점검 결과
- `archive/arxiv/papers.jsonl` ✅ 존재 (10편 arXiv 메타데이터)
- `archive/tavily_search.jsonl` ❌ 없음 (이번 런은 “검색 쿼리/추가 인덱스 부재”로 한계 표기 필요)
- `archive/openalex/works.jsonl` ❌ 없음
- `archive/youtube/videos.jsonl` ❌ 없음
- `archive/local/manifest.jsonl` ❌ 없음

### 실제 소스 구성(파일 단위)
- **arXiv (10편)**  
  - PDF 10개: `archive/arxiv/pdf/*.pdf`  
  - 텍스트 추출본 10개: `archive/arxiv/text/*.txt` (다이제스트/표/인용에 주로 사용 권장)
  - 메타데이터: `archive/arxiv/papers.jsonl` (발행일/저자/요약/링크/인용수 등)
- **NVIDIA Glossary 웹 덤프 (1개)**  
  - `archive/tavily_extract/0001_https_www.nvidia.com_en-us_glossary_generative-physical-ai.txt`  
  - 포함: “**Physical AI**” 정의 문장(“Physical AI lets autonomous systems…”) 및 스택(시뮬레이션/합성데이터/RL/런타임 컴퓨터 등) 설명

### 런/보고서 보조 파일(작성용)
- `archive/physical_ai_insight-index.md` (아카이브 목차/구성)
- `report_notes/source_index.jsonl` (소스 ID ↔ 파일 경로 매핑)
- `report_notes/source_triage.md` (라이트 트리아지 목록)
- `instruction/generated_prompt_physical_ai_insight.txt` (요구 섹션/정책/톤)

---

## 2) 구조화된 소스 인벤토리(보고서 포커스 기준)

### A. “Physical AI” 정의/스택 근거(필수)
1. **NVIDIA Glossary — “What is Physical AI?”**  
   - 파일: `archive/tavily_extract/0001_https_www.nvidia.com_en-us_glossary_generative-physical-ai.txt`  
   - 용도: Physical AI 정의 인용(필수), 기술 스택(시뮬레이션·합성데이터·RL·런타임) 개요 근거

### B. 10편 arXiv 논문(필수 다이제스트 대상)
- 메타데이터: `archive/arxiv/papers.jsonl`
- 텍스트 추출본: `archive/arxiv/text/{arxiv_id}.txt`
- PDF: `archive/arxiv/pdf/{arxiv_id}.pdf`

목록(요구된 10편):
1) Octo — 2405.12213v2  
2) OpenVLA — 2406.09246v3  
3) π0 — 2410.24164v4  
4) CogACT — 2411.19650v1  
5) RoboVLMs — 2412.14058v3  
6) Gemini Robotics — 2503.20020v1  
7) GR00T N1 — 2503.14734v2  
8) PD-VLA — 2503.02310v1  
9) RTC — 2506.07339v2  
10) BitVLA — 2506.07530v1  

### C. 커버리지/한계 명시용(필수 섹션 “공개정보 한계”에 사용)
- `archive/physical_ai_insight-index.md` 에 “Queries: 0 | URLs: 1 | arXiv IDs: 10” → **검색 쿼리/추가 외부 소스 부재** 근거로 사용 가능(인덱스 자체를 본문 근거로 인용하진 말고, 방법 섹션 서술에 활용)

---

## 3) 우선 읽기 목록(최대 12개) + 선정 이유(보고서 작성 효율 중심)

1. **NVIDIA Glossary: What is Physical AI?**  
   - `archive/tavily_extract/0001_https_www.nvidia.com_en-us_glossary_generative-physical-ai.txt`  
   - 이유: “Physical AI” 정의 **직접 인용 필수** + 스택/합성데이터/시뮬레이션/런타임 컴퓨팅 프레이밍 제공.

2. **OpenVLA (2406.09246v3) — text**  
   - `archive/arxiv/text/2406.09246v3.txt`  
   - 이유: 대표적인 **오픈 VLA**. “RT-2-X 대비 성능” 등 **의사결정용 수치/포지셔닝**이 요약에 포함되어 비교축 표의 기준점이 됨.

3. **Octo (2405.12213v2) — text**  
   - `archive/arxiv/text/2405.12213v2.txt`  
   - 이유: “Generalist robot policy” 트렌드의 출발점 격. 데이터 규모(“800k trajectories… Open X-Embodiment”) 및 **파인튜닝 실무성** 강조.

4. **π0 (2410.24164v4) — text**  
   - `archive/arxiv/text/2410.24164v4.txt`  
   - 이유: **flow matching 기반 VLA/정책** 축 담당. 이후 RTC(실시간)와 연결해 “flow + action chunking” 흐름을 설명하기 좋음.

5. **Real-Time Execution… RTC (2506.07339v2) — text**  
   - `archive/arxiv/text/2506.07339v2.txt`  
   - 이유: 보고서 필수 트렌드인 **실시간 실행/지연 내성(서빙)**의 핵심. “재학습 없이 적용” 같은 산업 적용 포인트가 큼.

6. **PD‑VLA (2503.02310v1) — text**  
   - `archive/arxiv/text/2503.02310v1.txt`  
   - 이유: **action chunking + 병렬 디코딩**으로 “처리량/제어주기” 축을 채움(서빙 표에 바로 반영 가능).

7. **BitVLA (2506.07530v1) — text**  
   - `archive/arxiv/text/2506.07530v1.txt`  
   - 이유: **압축/양자화(1-bit/저메모리)** 트렌드 담당. “엣지/온로봇 배치” 리스크·TCO 논의에 유용.

8. **GR00T N1 (2503.14734v2) — text**  
   - `archive/arxiv/text/2503.14734v2.txt`  
   - 이유: **휴머노이드 시스템** 섹션의 간판 소스. dual-system(추론/행동) 구조로 “아키텍처 패턴” 비교에 좋음.

9. **Gemini Robotics (2503.20020v1) — text**  
   - `archive/arxiv/text/2503.20020v1.txt`  
   - 이유: 대규모 멀티모달 기반 **산업적 방향성(가족 모델/안전 고려 언급)**을 담고 있어 경영진 요약/리스크 균형에 도움.

10. **CogACT (2411.19650v1) — text**  
   - `archive/arxiv/text/2411.19650v1.txt`  
   - 이유: “VLM에서 액션 모듈 분리/확장” 관점. OpenVLA와 대비되는 설계로 **아키텍처 선택지**를 풍부하게 함.

11. **RoboVLMs (2412.14058v3) — text**  
   - `archive/arxiv/text/2412.14058v3.txt`  
   - 이유: “What matters…” 형태의 **설계 요인/실험 가이드북**. 비교표의 “학습 레시피/백본 선택/데이터 혼합” 축 근거.

12. **arXiv 메타데이터 묶음 (papers.jsonl)**  
   - `archive/arxiv/papers.jsonl`  
   - 이유: 각 논문 다이제스트에 필요한 **발행일/업데이트/요약/URL** 일괄 확인. (특히 다이제스트의 메타데이터 문장 작성에 효율적)

---

## 4) 추천 읽기 순서(작업 플로우 제안)

1) **NVIDIA Glossary**로 정의/스택 프레임 확정 → “Physical AI 개요”, “리뷰 범위와 방법” 초안 작성  
2) **OpenVLA·Octo·RoboVLMs**로 “Generalist/VLA” 핵심 축 정리(비교표 골격 생성)  
3) **π0 → PD‑VLA → RTC**로 “flow/action chunking/실시간 실행(서빙)” 축 채우기  
4) **BitVLA**로 “압축/양자화·온디바이스” 축 및 TCO/공급망 리스크 포인트 수집  
5) **GR00T N1·Gemini Robotics**로 “휴머노이드/시스템·안전/거버넌스” 축 보강  
6) **CogACT**로 아키텍처 대비 및 다이제스트의 “강점/한계/재현성” 코멘트 보완  
7) 마지막으로 **PDF(필요한 경우만)**: 텍스트 추출본에서 표/수치/세부 실험 설정이 누락되거나 깨진 부분을 PDF로 교차 확인

---

## 5) 오프토픽/누락 주의(보고서에 명시할 공개정보 한계)

- 이번 아카이브에는 **Tavily Search 결과, OpenAlex, YouTube 인덱스 파일이 존재하지 않음** → “검색 쿼리·추가 인덱스 부재” 및 “외부 검증/시장·규제 동향”은 다루지 못함을 **공개정보 한계**로 표기 필요.
- 산업 적용 리스크(규제/책임/IP 등)는 **논문 및 NVIDIA Glossary에 근거한 범위 내**에서만 정리(추정 금지).