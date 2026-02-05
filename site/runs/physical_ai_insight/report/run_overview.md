# Run Overview

## Instruction
Source: ./instruction/generated_prompt_physical_ai_insight.txt

```
Language: Korean

Template: custom_mit_tech_review
Depth: normal

목적/범위: arXiv에서 수집된 “Physical AI” 관련 10편 논문과 NVIDIA Glossary(웹 덤프) 1개를 근거로, 기술 경영진/연구·제품 이해관계자가 의사결정에 활용할 수 있는 기술 리뷰를 작성하라. 연구 트렌드(Generalist robot policy, VLA, flow/action chunking, 실시간 실행, 압축/양자화, 휴머노이드 시스템)와 산업 적용 시 리스크를 균형 있게 다룬다.

핵심 포함 항목(필수 섹션별 최소 요구):
- 표지: 제목(예: “Physical AI 기술 리뷰”), 부제(한 문장 키메시지), 작성자/소속, 버전, 날짜, Run ID(physical_ai_insight).
- 경영진 요약: 핵심 발견 3–5개(근거 포함), 사업/연구 함의, 즉시 액션(파일럿/파트너십/투자) 제안, “공개정보 한계” 1개 항목.
- Physical AI 개요: 첫 등장에 “Physical AI” 정의(NVIDIA “What is Physical AI?” 인용), 기술 스택과 대표 응용, 현재 한계 1–2문장.
- 리뷰 범위와 방법: 소스가 arXiv 10편(+NVIDIA 웹)임을 명시, 포함/제외 기준과 평가 프레임(신규성/실증 강도/재현성/산업 적합성) 제시. (검색 쿼리·추가 인덱스는 이번 런에 부재 → 공개정보 한계로 표기)
- 논문 다이제스트: Octo(2405.12213), OpenVLA(2406.09246), π0(2410.24164), CogACT(2411.19650), RoboVLMs(2412.14058), Gemini Robotics(2503.20020), GR00T N1(2503.14734), PD-VLA(2503.02310), RTC(2506.07339), BitVLA(2506.07530) 각각 250–400자. 메타데이터+기여+방법/데이터+결과(수치 있으면)+강점/한계+산업 함의/리스크+재현성(코드/데이터 공개 여부).
- 비교 분석 및 동향: 과제/모달리티/액션 표현/학습 패러다임/실증 수준/서빙(지연·처리량)/압축 축으로 표 1개 이상.
- 미래 전망과 로드맵: 0–12/12–36/36개월+로 성과·브레이크스루·KPI, 기술/데이터/인력/규제 과제 분리.
- 산업적 비판과 리스크: 안전/책임/규제/IP/재현성/공급망/TCO를 현실적으로 평가, 완화 전략 vs 잔여 불확실성 구분.
- 권고 사항: 우선순위(Why now/근거/선행조건)와 함께 5개 내외 액션.
- 부록: 용어집, 참고문헌(arXiv ID/URL), 데이터·코드 링크(있을 때만), 평가 시트 요약.

증거/인용 정책: 모든 핵심 주장에는 해당 논문(arXiv ID) 또는 NVIDIA Glossary를 괄호 인용으로 연결하라. 텍스트 추출본/웹 덤프에 없는 내용(인용수, 시장규모, 규제 동향, 경쟁사 내부 성능 등)은 추정하지 말고 “공개정보 한계”로 명시하라.

언어/톤: 한국어로, 친절하고 부드럽지만 과장 없이 근거 중심. 불확실성은 범위/조건(실험 환경, 데이터 규모, 재현성)과 함께 서술하고, 표/그림에는 캡션과 “so-what” 1문장을 붙여라.
```

## Archive Index
Source: ./archive/physical_ai_insight-index.md

# Archive physical_ai_insight

- Query ID: `physical_ai_insight`
- Date: 2026-02-06 (range: last 365 days)
- Queries: 0 | URLs: 1 | arXiv IDs: 10

## Run Command
- `python -m feather --input C:\Users\angpa\myProjects\FEATHER\site\runs\physical_ai_insight\instruction\physical_ai_insight.txt --output C:\Users\angpa\myProjects\FEATHER\site\runs --days 365 --max-results 8 --download-pdf --lang en --openalex --oa-max-results 8 --youtube --yt-transcript --update-run`

## Instruction
- `../instruction/physical_ai_insight.txt`

## Tavily Extract
- `./tavily_extract/0001_https_www.nvidia.com_en-us_glossary_generative-physical-ai.txt`

## arXiv
- `./arxiv/papers.jsonl`
- PDFs: 10
- PDF file: `./arxiv/pdf/2405.12213v2.pdf` | Title: Octo: An Open-Source Generalist Robot Policy | Source: https://arxiv.org/pdf/2405.12213v2 | Citations: 7
- PDF file: `./arxiv/pdf/2406.09246v3.pdf` | Title: OpenVLA: An Open-Source Vision-Language-Action Model | Source: https://arxiv.org/pdf/2406.09246v3 | Citations: 34
- PDF file: `./arxiv/pdf/2410.24164v4.pdf` | Title: $π_0$: A Vision-Language-Action Flow Model for General Robot Control | Source: https://arxiv.org/pdf/2410.24164v4 | Citations: 6
- PDF file: `./arxiv/pdf/2411.19650v1.pdf` | Title: CogACT: A Foundational Vision-Language-Action Model for Synergizing Cognition and Action in Robotic Manipulation | Source: https://arxiv.org/pdf/2411.19650v1 | Citations: 5
- PDF file: `./arxiv/pdf/2412.14058v3.pdf` | Title: Towards Generalist Robot Policies: What Matters in Building Vision-Language-Action Models | Source: https://arxiv.org/pdf/2412.14058v3 | Citations: 0
- PDF file: `./arxiv/pdf/2503.02310v1.pdf` | Title: Accelerating Vision-Language-Action Model Integrated with Action Chunking via Parallel Decoding | Source: https://arxiv.org/pdf/2503.02310v1 | Citations: 0
- PDF file: `./arxiv/pdf/2503.14734v2.pdf` | Title: GR00T N1: An Open Foundation Model for Generalist Humanoid Robots | Source: https://arxiv.org/pdf/2503.14734v2 | Citations: 3
- PDF file: `./arxiv/pdf/2503.20020v1.pdf` | Title: Gemini Robotics: Bringing AI into the Physical World | Source: https://arxiv.org/pdf/2503.20020v1 | Citations: 3
- PDF file: `./arxiv/pdf/2506.07339v2.pdf` | Title: Real-Time Execution of Action Chunking Flow Policies | Source: https://arxiv.org/pdf/2506.07339v2 | Citations: 0
- PDF file: `./arxiv/pdf/2506.07530v1.pdf` | Title: BitVLA: 1-bit Vision-Language-Action Models for Robotics Manipulation | Source: https://arxiv.org/pdf/2506.07530v1 | Citations: 0
- Extracted texts: 10

- Text file: `./arxiv/text/2405.12213v2.txt` | Title: Octo: An Open-Source Generalist Robot Policy | Source: https://arxiv.org/pdf/2405.12213v2 | Citations: 7
- Text file: `./arxiv/text/2406.09246v3.txt` | Title: OpenVLA: An Open-Source Vision-Language-Action Model | Source: https://arxiv.org/pdf/2406.09246v3 | Citations: 34
- Text file: `./arxiv/text/2410.24164v4.txt` | Title: $π_0$: A Vision-Language-Action Flow Model for General Robot Control | Source: https://arxiv.org/pdf/2410.24164v4 | Citations: 6
- Text file: `./arxiv/text/2411.19650v1.txt` | Title: CogACT: A Foundational Vision-Language-Action Model for Synergizing Cognition and Action in Robotic Manipulation | Source: https://arxiv.org/pdf/2411.19650v1 | Citations: 5
- Text file: `./arxiv/text/2412.14058v3.txt` | Title: Towards Generalist Robot Policies: What Matters in Building Vision-Language-Action Models | Source: https://arxiv.org/pdf/2412.14058v3 | Citations: 0
- Text file: `./arxiv/text/2503.02310v1.txt` | Title: Accelerating Vision-Language-Action Model Integrated with Action Chunking via Parallel Decoding | Source: https://arxiv.org/pdf/2503.02310v1 | Citations: 0
- Text file: `./arxiv/text/2503.14734v2.txt` | Title: GR00T N1: An Open Foundation Model for Generalist Humanoid Robots | Source: https://arxiv.org/pdf/2503.14734v2 | Citations: 3
- Text file: `./arxiv/text/2503.20020v1.txt` | Title: Gemini Robotics: Bringing AI into the Physical World | Source: https://arxiv.org/pdf/2503.20020v1 | Citations: 3
- Text file: `./arxiv/text/2506.07339v2.txt` | Title: Real-Time Execution of Action Chunking Flow Policies | Source: https://arxiv.org/pdf/2506.07339v2 | Citations: 0
- Text file: `./arxiv/text/2506.07530v1.txt` | Title: BitVLA: 1-bit Vision-Language-Action Models for Robotics Manipulation | Source: https://arxiv.org/pdf/2506.07530v1 | Citations: 0
