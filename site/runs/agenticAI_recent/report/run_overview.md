# Run Overview

## Instruction
Source: ./instruction/agenticAI_recent.txt

```
최근 3~6개월 내 Agentic AI의 "핫이슈/논쟁/리스크"를 8개 항목으로 정리하라.

범주: 보안(프롬프트 인젝션/툴 오남용), 신뢰성(계획 실패/환각), 비용/지연, 평가 난제, 데이터 거버넌스, 멀티에이전트 상호작용 리스크, 책임소재/감사, 엔터프라이즈 도입 패턴

각 이슈: 무엇이 문제인가 / 왜 지금 부상했나 / 대표 사례/참고 링크 / 대응 전략(기술+프로세스)
```

## Archive Index
Source: ./archive/agenticAI_recent-index.md

# Archive agenticAI_recent

- Query ID: `agenticAI_recent`
- Date: 2026-02-08 (range: last 365 days)
- Queries: 3 | URLs: 0 | arXiv IDs: 0

## Run Command
- `python -m feather --input C:\Users\angpa\myProjects\FEATHER\site\runs\agenticAI_recent\instruction\agenticAI_recent.txt --output C:\Users\angpa\myProjects\FEATHER\site\runs --days 365 --max-results 8 --download-pdf --lang en --openalex --oa-max-results 8 --update-run --agentic-search --max-iter 3`

## Instruction
- `../instruction/agenticAI_recent.txt`

## Tavily Search
- `./tavily_search.jsonl`
- Includes per-result `summary` and `query_summary`

## YouTube
- `./youtube/videos.jsonl`
- Transcripts: 0

## OpenAlex (OA)
- `./openalex/works.jsonl`
- PDFs: 2
- PDF file: `./openalex/pdf/W2921187241.pdf` | Title: From Skynet to Siri: an exploration of the nature and effects of media coverage of artificial intelligence | Source: http://udspace.udel.edu/handle/19716/24048 | Citations: 25
- PDF file: `./openalex/pdf/W4415728083.pdf` | Title: Alignment Problem as Cultural and Legal Challenge: Artificial Intelligence, Interpretability, and Searching for Sense | Source: https://journals.umcs.pl/sil/article/download/20001/pdf | Citations: 0
- Extracted texts: 2
- Text file: `./openalex/text/W2921187241.txt` | Title: From Skynet to Siri: an exploration of the nature and effects of media coverage of artificial intelligence | Source: http://udspace.udel.edu/handle/19716/24048 | Citations: 25
- Text file: `./openalex/text/W4415728083.txt` | Title: Alignment Problem as Cultural and Legal Challenge: Artificial Intelligence, Interpretability, and Searching for Sense | Source: https://journals.umcs.pl/sil/article/download/20001/pdf | Citations: 0

## arXiv
- `./arxiv/papers.jsonl`
- PDFs: 7
- PDF file: `./arxiv/pdf/2602.06034v1.pdf` | Title: V-Retrver: Evidence-Driven Agentic Reasoning for Universal Multimodal Retrieval | Source: https://arxiv.org/pdf/2602.06034v1 | Citations: 0
- PDF file: `./arxiv/pdf/2602.06035v1.pdf` | Title: InterPrior: Scaling Generative Control for Physics-Based Human-Object Interactions | Source: https://arxiv.org/pdf/2602.06035v1 | Citations: 0
- PDF file: `./arxiv/pdf/2602.06038v1.pdf` | Title: CommCP: Efficient Multi-Agent Coordination via LLM-Based Communication with Conformal Prediction | Source: https://arxiv.org/pdf/2602.06038v1 | Citations: 0
- PDF file: `./arxiv/pdf/2602.06039v1.pdf` | Title: DyTopo: Dynamic Topology Routing for Multi-Agent Reasoning via Semantic Matching | Source: https://arxiv.org/pdf/2602.06039v1 | Citations: 0
- PDF file: `./arxiv/pdf/2602.06040v1.pdf` | Title: SwimBird: Eliciting Switchable Reasoning Mode in Hybrid Autoregressive MLLMs | Source: https://arxiv.org/pdf/2602.06040v1 | Citations: 0
- PDF file: `./arxiv/pdf/2602.06041v1.pdf` | Title: Predicting Camera Pose from Perspective Descriptions for Spatial Reasoning | Source: https://arxiv.org/pdf/2602.06041v1 | Citations: 0
- PDF file: `./arxiv/pdf/2602.06043v1.pdf` | Title: Shared LoRA Subspaces for almost Strict Continual Learning | Source: https://arxiv.org/pdf/2602.06043v1 | Citations: 0
- Extracted texts: 7

- Text file: `./arxiv/text/2602.06034v1.txt` | Title: V-Retrver: Evidence-Driven Agentic Reasoning for Universal Multimodal Retrieval | Source: https://arxiv.org/pdf/2602.06034v1 | Citations: 0
- Text file: `./arxiv/text/2602.06035v1.txt` | Title: InterPrior: Scaling Generative Control for Physics-Based Human-Object Interactions | Source: https://arxiv.org/pdf/2602.06035v1 | Citations: 0
- Text file: `./arxiv/text/2602.06038v1.txt` | Title: CommCP: Efficient Multi-Agent Coordination via LLM-Based Communication with Conformal Prediction | Source: https://arxiv.org/pdf/2602.06038v1 | Citations: 0
- Text file: `./arxiv/text/2602.06039v1.txt` | Title: DyTopo: Dynamic Topology Routing for Multi-Agent Reasoning via Semantic Matching | Source: https://arxiv.org/pdf/2602.06039v1 | Citations: 0
- Text file: `./arxiv/text/2602.06040v1.txt` | Title: SwimBird: Eliciting Switchable Reasoning Mode in Hybrid Autoregressive MLLMs | Source: https://arxiv.org/pdf/2602.06040v1 | Citations: 0
- Text file: `./arxiv/text/2602.06041v1.txt` | Title: Predicting Camera Pose from Perspective Descriptions for Spatial Reasoning | Source: https://arxiv.org/pdf/2602.06041v1 | Citations: 0
- Text file: `./arxiv/text/2602.06043v1.txt` | Title: Shared LoRA Subspaces for almost Strict Continual Learning | Source: https://arxiv.org/pdf/2602.06043v1 | Citations: 0

## Agentic Trace
- `./agentic_trace.jsonl`
- `./agentic_trace.md`
