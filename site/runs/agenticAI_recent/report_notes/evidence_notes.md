Executive Summary
Agentic AI는 자율적 기획·도구 사용·다중 에이전트 상호작용을 통해 장기 과제를 실행하는 LLM 기반 시스템이며, 프롬프트 인젝션은 입력/메모리/툴 경로에 혼입되어 정책을 우회하게 만드는 공격 기법, MCP(Model Context Protocol)는 에이전트-툴-리소스 간 표준화된 컨텍스트 교환 프로토콜이다. 최근 연구는 성능과 신뢰성을 크게 높이는 동시에, 통신/툴 사용 로그를 통해 감사 가능성을 강화할 수 있음을 보여준다. 그러나 지금 결정을 미루면 (1) 툴 오남용·권한 상승 등 보안 사고로 직접 비용과 규제 리스크가 급증하고, (2) 비효율적 에이전트 상호작용으로 인한 토큰/지연 낭비가 누적되며, (3) 모델 업데이트·버전관리 실패로 회귀(regression)와 운영 중단이 발생한다. 반대로, 동적 라우팅·통신 캘리브레이션·증거 기반 툴 사용·지속학습 구조를 조기 도입하면 성능-비용-감사성의 동시 개선이 가능하다(DyTopo, CommCP, V-Retrver, SwimBird, Share). 특히 DyTopo는 라운드별 토폴로지 트레이스를 남겨 책임·감사에 유리하며, CommCP는 탐색시간을 단축해 운영비를 절감한다(수치 근거 하단 인용 참조). (DyTopo: 2026; ./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1) (CommCP: 2026; ./archive/arxiv/text/2602.06038v1.txt; https://arxiv.org/abs/2602.06038v1)

Key Findings
- 주장: 동적 통신 토폴로지와 매니저-중재(halting) 정책은 다중 에이전트 추론의 정확도와 감사 가능성을 동시에 개선한다 → 증거: DyTopo는 16개 백본×데이터셋 전 설정에서 최고 성능, 평균 +6.09pt 개선 및 라운드별 그래프 트레이스를 제공(예: HumanEval 92.07% at 5 rounds; Math-500 87.14% at 9 rounds) → 사업 임팩트: 품질 향상과 함께 “설명 가능한 상호작용 로그”를 감사·규제 대응 근거로 활용 가능(개발 결함 디버깅/원인 규명 단축) (DyTopo: 2026; ./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1)
- 주장: 메시지 신뢰도 캘리브레이션(Conformal Prediction)은 에이전트 간 “잡음 통신”을 줄여 성공률과 시간 효율을 개선한다 → 증거: CommCP는 2로봇 MM-EQA에서 SR 0.68@NTC 0.4(기준 MMFBE SR 0.65@NTC 0.8), 평균 완료시간 445s vs 594s, 비공유·비캘리브레이션 대비 일관된 우위 → 사업 임팩트: 운영 지연·토큰 비용 절감, 다중 봇/로봇 워크플로의 MTTA/MTTR 개선 (CommCP: 2026; ./archive/arxiv/text/2602.06038v1.txt; https://arxiv.org/abs/2602.06038v1)
- 주장: 증거 중심(툴-유도) 추론은 멀티모달 검색에서 신뢰성과 일반화를 동시에 높인다 → 증거: V-Retrver가 M-BEIR 평균 Recall 69.7%(+4.9%p vs U-MARVEL-7B), CIRCO MAP@5 48.2, 미학습 태스크 평균 Recall 61.1%로 SOTA 대비 우위; 시각툴(SELECT-IMAGE, ZOOM-IN)과 EAPO로 불필요 툴 호출 억제 → 사업 임팩트: 에이전트의 툴 사용 정책·로그 기반 게이팅으로 품질·비용 최적화 (V-Retrver: 2026; ./archive/arxiv/text/2602.06034v1.txt; https://arxiv.org/abs/2602.06034v1)
- 주장: 입력별 추론 모드 전환은 시각·언어 혼합 업무에서 비용-지연-정확도 트레이드오프를 최적화한다 → 증거: SwimBird는 V* Bench 85.5, HR-Bench 4K/8K 79.0/74.9, MMStar 71.2, WeMath 49.5로 고해상·고난도 과제에서 고성능; 동적 latent 토큰 상한 32가 최적 → 사업 임팩트: 워크로드·해상도·난이도에 맞춘 토큰 예산 정책으로 인프라 비용 절감 (SwimBird: 2026; ./archive/arxiv/text/2602.06040v1.txt; https://arxiv.org/abs/2602.06040v1)
- 주장: Shared LoRA Subspaces는 거의 엄격한 지속학습을 저비용으로 실현한다 → 증거: GLUE 평균 83.44%를 0.012M 파라미터(0.29MB)로 달성 vs LoRA 7.2M(81.6MB), 최대 100× 파라미터·281× 메모리 절감; 이미지 분류/3D 포즈/T2I에서도 효율성 입증 → 사업 임팩트: 모델 업데이트·롤백 비용 급감, 버전·감사 체계 단순화 (Shared LoRA Subspaces: 2026; ./archive/arxiv/text/2602.06043v1.txt; https://arxiv.org/abs/2602.06043v1)

Decision Implications
- 즉시(0–3개월): 다중 에이전트 상호작용에 DyTopo형 “라운드별 동적 라우팅+조기종료”를 파일럿 도입. 성공 기준·토폴로지 임계값(예: 0.3~0.4)·라운드 예산(5~9)을 태스크별로 캘리브레이트하고, 그래프·메시지 로그를 표준 감사 아티팩트로 저장한다(품질·감사 강화) (DyTopo: 2026; ./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1)
- 즉시(0–3개월): 멀티에이전트 통신에 Conformal Prediction을 적용해 메시지 공유 임계값을 운영 환경에 맞게 설정(Option A/B별 분리, 예시 0.6/0.82 분위)하고, 답변공유를 활성화해 중복 탐색 제거(지연·비용 절감) (CommCP: 2026; ./archive/arxiv/text/2602.06038v1.txt; https://arxiv.org/abs/2602.06038v1)
- 즉시(0–3개월): 에이전트 툴 사용은 증거-검증 루프(EAPO/GRPO 등)로 학습·평가하고, 툴 호출 로그 스키마(툴 선택·영역·보상)를 표준화. MCP 게이트웨이 또는 동등 제어면을 통해 자격증명/권한을 최소권한 원칙으로 게이팅한다(보안·비용 통제) (V-Retrver: 2026; ./archive/arxiv/text/2602.06034v1.txt; https://arxiv.org/abs/2602.06034v1)
- 중기(3–12개월): 모델 업데이트는 Share 서브스페이스를 기본 경로로 표준화(공유 기저+작은 계수만 학습). 롤백·A/B·감사에 유리한 버전 정책을 수립하고, 고빈도 태스크에선 SwimBird형 모드 스위칭으로 토큰 예산을 동적으로 집행(인프라 TCO 최적화) (Shared LoRA Subspaces: 2026; ./archive/arxiv/text/2602.06043v1.txt; https://arxiv.org/abs/2602.06043v1) (SwimBird: 2026; ./archive/arxiv/text/2602.06040v1.txt; https://arxiv.org/abs/2602.06040v1)

Risks & Gaps
- 상위 리스크
  - 툴 오남용/권한상승(프롬프트 인젝션 포함): 에이전트가 고권한 툴을 오조작하거나 외부 입력에 의해 정책 우회. 링크 수준 참고: OWASP가 에이전트 툴 오남용을 중대 위협으로 경고 (https://www.infoq.com/news/2025/09/owasp-agentic-ai-security/) (링크 수준)·MCP 게이트웨이 보안 논의 (https://www.prompt.security/blog/security-for-agentic-ai-unveiling-mcp-gateway-mcp-risk-assessment) (링크 수준)
  - 평가/감사 블라인드 스팟: 언어적 CoT만으로 “합리화”가 생성되어 사실상 검증이 누락될 위험. 증거-검증·토폴로지 트레이스 의무화로 완화 필요 (V-Retrver, DyTopo 근거) (./archive/arxiv/text/2602.06034v1.txt; https://arxiv.org/abs/2602.06034v1) (./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1)
  - 문화·법제 정합성 미흡: 해석가능성·불확정성·지식추출 논쟁에 대한 조직적 대응 부재 시 규제/사회적 신뢰 리스크 확대 (Alignment Problem as Cultural and Legal Challenge: 2025; ./archive/openalex/text/W4415728083.txt; https://doi.org/10.17951/sil.2025.34.2.441-479)
- 다음 1–2주 검증 과제
  - 보안: 고위험 툴(결제/코드/파일 I/O) 경로에 레드팀·프롬프트 인젝션 테스트 수행, MCP/프록시 레이어에서 권한·비밀관리 점검(로그 샘플 감사). 링크 수준 참조: Emergent Mind 위협 택소노미 (https://www.emergentmind.com/topics/agentic-ai-security) (링크 수준)
  - 성능/비용: DyTopo 파일럿(2~3 워크로드)로 라운드 예산·임계값 최적화, CommCP 적용 전/후 평균 처리시간·토큰 사용 비교
  - 감사: V-Retrver형 툴 호출 로그 스키마 PoC(선택·영역·보상), SwimBird형 모드-토큰 정책이 비용에 미치는 영향 계측
- 공개정보 한계
  - archive/local/manifest.jsonl 부재로 추가 로컬 레퍼런스의 식별·활용에 제약이 있음(공개정보 한계로 표기).
  - YouTube는 트랜스크립트 부재로 “사례/관점” 수준 인용만 가능.

Appendix
A. 8개 이슈 요약(범주/요약/사례·링크/대응 전략)
- 보안
  - 요약: 프롬프트 인젝션·툴 오남용·권한상승·메모리 포이즈닝 등 A2A/MCP 경로 전반 리스크
  - 사례·링크: OWASP 툴 오남용 경고(링크 수준) https://www.infoq.com/news/2025/09/owasp-agentic-ai-security/; MCP 게이트웨이(링크 수준) https://www.prompt.security/blog/security-for-agentic-ai-unveiling-mcp-gateway-mcp-risk-assessment; Emergent Mind 위협 택소노미(링크 수준) https://www.emergentmind.com/topics/agentic-ai-security
  - 대응: 최소권한·툴 화이트리스트·비밀 분리; MCP/프록시 정책 엔진; 레드팀·정책 우회 탐지 룰; 툴 호출/결과 무결성 로그
- 신뢰성
  - 요약: 동적 라우팅·통신 캘리브레이션·증거 검증으로 에이전트 품질 향상
  - 사례·링크: DyTopo 성능+트레이스(./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1); CommCP 성공률·시간 개선(./archive/arxiv/text/2602.06038v1.txt; https://arxiv.org/abs/2602.06038v1)
  - 대응: 라운드별 목표·임계값 관리; CP 기반 메시지 필터; 실패·수정 루프 계측
- 비용·지연
  - 요약: 모드 스위칭·라운드 예산·툴 게이팅으로 토큰/지연 최적화
  - 사례·링크: SwimBird Nmax=32 최적, 고난도 벤치 고성능(./archive/arxiv/text/2602.06040v1.txt; https://arxiv.org/abs/2602.06040v1); CommCP 평균 445s vs 594s (./archive/arxiv/text/2602.06038v1.txt; https://arxiv.org/abs/2602.06038v1)
  - 대응: 난이도·해상도·질의 유형별 동적 정책; 속도-성공률 곡선 기반 SLO
- 평가
  - 요약: 텍스트 CoT 단독 평가 한계 → 증거 수집·검증·토폴로지 트레이스 기반 평가체계 필요
  - 사례·링크: V-Retrver EAPO로 툴 남용 억제+성능 향상(./archive/arxiv/text/2602.06034v1.txt; https://arxiv.org/abs/2602.06034v1); DyTopo 라운드별 그래프 해석 (./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1)
  - 대응: 툴 호출 근거 로그·보상함수 정합성 점검; 그래프 변화-성공 상관 분석
- 데이터 거버넌스
  - 요약: 지속학습·버전/롤백·감사 구조가 핵심; 지식추출/투명성 이슈 병행
  - 사례·링크: Share—최대 100× 파라미터·281× 메모리 절감(./archive/arxiv/text/2602.06043v1.txt; https://arxiv.org/abs/2602.06043v1); 문화·법제 관점의 지식추출·투명성 논의(./archive/openalex/text/W4415728083.txt; https://doi.org/10.17951/sil.2025.34.2.441-479)
  - 대응: 공유 서브스페이스 표준화, 전·후 성능·안전 감사; 데이터 출처·권리 관리
- 멀티에이전트 상호작용
  - 요약: 고정 토폴로지 한계 → 라운드별 적응·선택적 메시징
  - 사례·링크: DyTopo 동적 라우팅·싱크 배리어 (./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1); CommCP 분산·자율 통신(./archive/arxiv/text/2602.06038v1.txt; https://arxiv.org/abs/2602.06038v1)
  - 대응: 매니저 메타-정책, 라운드 목표·종료 기준 관리
- 책임·감사
  - 요약: 해석가능성·불확정성·지식추출의 법·문화 프레임 필요, 투명성·감사 가능 로그 확보
  - 사례·링크: 문화·법제 프레임 및 투명성의 중요성 (./archive/openalex/text/W4415728083.txt; https://doi.org/10.17951/sil.2025.34.2.441-479)
  - 대응: 라운드·툴 로그의 보존·검토 의무화, KPI: 감사 재현성·추적성
- 엔터프라이즈 도입 패턴
  - 요약: 파일럿 지옥 회피, 보안·평가·거버넌스 일체형 스케일 전략 필요
  - 사례·링크: McKinsey 엔터프라이즈 보안·거버넌스 플레이북(링크 수준) https://www.mckinsey.com/capabilities/risk-and-resilience/our-insights/deploying-agentic-ai-with-safety-and-security-a-playbook-for-technology-leaders; 업계 관점 YouTube(트랜스크립트 부재, 관점 수준)
  - 대응: 단계별 가드레일·KPI·리스크 레지스터; 보안·평가·모델관리 동시 설계

B. 주요 참고문헌/링크(소스 유형별)
- arXiv 원문(직접 인용)
  - DyTopo: Dynamic Topology Routing for Multi-Agent Reasoning via Semantic Matching (2026). ./archive/arxiv/text/2602.06039v1.txt; https://arxiv.org/abs/2602.06039v1
  - CommCP: Efficient Multi-Agent Coordination via LLM-Based Communication with Conformal Prediction (2026). ./archive/arxiv/text/2602.06038v1.txt; https://arxiv.org/abs/2602.06038v1
  - V-Retrver: Evidence-Driven Agentic Reasoning for Universal Multimodal Retrieval (2026). ./archive/arxiv/text/2602.06034v1.txt; https://arxiv.org/abs/2602.06034v1
  - SwimBird: Eliciting Switchable Reasoning Mode in Hybrid Autoregressive MLLMs (2026). ./archive/arxiv/text/2602.06040v1.txt; https://arxiv.org/abs/2602.06040v1
  - Shared LoRA Subspaces for almost Strict Continual Learning (2026). ./archive/arxiv/text/2602.06043v1.txt; https://arxiv.org/abs/2602.06043v1
- OpenAlex 논문(직접 인용)
  - Alignment Problem as Cultural and Legal Challenge: Artificial Intelligence, Interpretability, and Searching for Sense (2025). ./archive/openalex/text/W4415728083.txt; https://doi.org/10.17951/sil.2025.34.2.441-479
- 웹/산업 보고(링크 수준 참고)
  - Agentic AI Security: Risks and Defenses – Emergent Mind: https://www.emergentmind.com/topics/agentic-ai-security
  - OWASP Flags Tool Misuse as Critical Threat for Agentic AI – InfoQ: https://www.infoq.com/news/2025/09/owasp-agentic-ai-security/
  - Agentic AI Security: MCP Gateway & Risk Assessment – Prompt Security: https://www.prompt.security/blog/security-for-agentic-ai-unveiling-mcp-gateway-mcp-risk-assessment
  - Agentic AI security: Risks & governance for enterprises – McKinsey: https://www.mckinsey.com/capabilities/risk-and-resilience/our-insights/deploying-agentic-ai-with-safety-and-security-a-playbook-for-technology-leaders
- YouTube(관점 수준)
  - IBM Technology: Risks of Agentic AI (2025-05-15)
  - This Week in Startups Clips: The Hidden Security Risks of Agentic AI (2025-05-13)
  - SCB 10X: From Pilot to Enterprise-Wide: Scaling AI Across the Organization (2025-11-05)

Notes on Source Coverage
- 인덱스/메타: archive/agenticAI_recent-index.md 확인.
- 로컬 핵심 소스 5편(arXiv)과 법·문화 논문(OpenAlex) 직접 인용 가능.
- 보안·MCP는 로컬 심층 논문 부재로 웹 링크 수준만 활용.
- YouTube는 트랜스크립트 없음 → 사례/관점 수준 언급으로 제한.