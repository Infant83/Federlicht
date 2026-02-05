# Template Adjustment

Template: default
Format: html
Language: Korean
Adjust mode: extend

## Rationale
Updated guidance to reflect user request: keep template section key as 'Executive Summary' but display the heading as 'Summary' and rewrite that section in natural prose without '관찰/권고' labels; no other sections changed.

## Required Sections (prompt-derived)
- Executive Summary
- Scope & Methodology
- Risks & Gaps
- Critics
- Appendix

## Sections (original)
- Executive Summary
- Scope & Methodology
- Key Findings
- Trends & Implications
- Risks & Gaps
- Critics
- Appendix

## Sections (adjusted)
- Executive Summary
- Scope & Methodology
- Key Findings
- Trends & Implications
- Risks & Gaps
- Critics
- Appendix

## Added Sections
(none)

## Removed Sections
(none)

## Guidance Overrides
- Executive Summary: 표제는 문서 내에서는 'Summary'로 표시하되(템플릿 상 섹션 키는 Executive Summary 유지), 본문은 두 단락으로 구성한다: 첫 단락(lede) 3문장 이하, 두 번째 단락(deck) 3문장 이하. 불릿 금지. 기존 '관찰/권고' 라벨은 제거하고 자연스러운 서술형 문장으로 재구성하되, 인용과 출처 표기는 유지한다. 다른 섹션의 라벨링 규칙에는 영향을 주지 않는다.
- Scope & Methodology: 보고 범위(주제 포함/제외), 사용 데이터/문헌/내부 자료, 평가/분석 절차, 도구/환경, 한계(공개정보 한계 등)를 명확히 기술한다. 방법의 재현 가능성을 높이기 위해 소스 경로(DOI/URL/아카이브 경로)와 버전/접근일을 기재한다.
- Key Findings: 핵심 발견을 간결한 단락들로 요약한다. 이 섹션에서는 기존 라벨링 원칙(관찰/추정/권고)을 유지하고, 각 주장에 최소 1개 출처를 첨부한다. 과장된 표현을 피하고 실행 함의를 분명히 한다.
- Trends & Implications: 주요 변화 흐름과 그 조직적/제품적 함의를 1–2단락으로 정리한다. '에이전트=앱'이 아니라 '에이전트=운영되는 워크플로우'로의 이동을 명시한다. 라벨링 원칙(관찰/추정/권고)을 유지한다.
- Risks & Gaps: 증거 공백, 부정적 시나리오, 미지수, 데이터 편향/가용성 한계를 체계적으로 기술한다. 특히 arXiv HTML 로컬 보존 부재, YouTube 원문 부재, 1차 보안 실증자료 제약을 '공개정보 한계'로 명시한다. 완화 방안은 '권고' 라벨로 제시한다.
- Critics: 대표적 비판을 헤드라인형 문장으로 제시하고, 각 항목에 대해 간단한 반론과 근거 수준(높음/중간/낮음)을 병기한다. 과도한 일반화는 피하고 인용을 제공한다.
- Appendix: 사용 소스 목록(DOI/URL/아카이브 경로/로컬 경로), 용어 정의, 가정·제외 범위를 포함한다. 내부 파일 경로가 있을 경우 명시하고, 홍보성 가능성이 있는 출처는 주석으로 표시한다. 별도의 References 섹션은 추가하지 않는다.

## Writer Guidance Additions
- 요청된 변경 범위는 Executive Summary(문서 내 표제: 'Summary') 섹션에 한정한다. 다른 섹션의 구조·콘텐츠는 변경하지 않는다.
- Executive Summary 본문에서는 '관찰/권고' 라벨을 제거하고 자연문으로 재서술하되, 인용·출처 표기는 유지한다.
- 내비게이션/목차에서 '실행 요약'으로 연결되는 앵커가 있을 경우 'Summary'로 동기화한다.
- 언어는 한국어, 출력은 HTML을 유지한다. 불릿은 Summary에서만 금지한다.
- 벤더/목록형 출처는 '홍보성 가능성' 주석을 유지하고, 원문 부재 시 '공개정보 한계'를 명시한다.
- 필수 섹션(Executive Summary, Scope & Methodology, Risks & Gaps, Critics, Appendix)은 그대로 유지한다. 섹션 키 이름은 변경하지 말고, Summary 표기는 Executive Summary의 표시명으로만 적용한다.
