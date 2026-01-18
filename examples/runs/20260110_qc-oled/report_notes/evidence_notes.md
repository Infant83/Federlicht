## 1) 1차 문헌(논문/리뷰; OpenAlex TXT/PDF 확보)

### A. *Using GNN property predictors as molecule generators* (Nature Communications, 2025)
- **GNN 기반 물성 예측기(property predictor)를 “생성기(generator)”로 전용**: 사전학습된 GNN의 가중치는 고정한 채, 입력인 분자 그래프(인접행렬 A, 특징행렬 F)를 **그래디언트 상승(gradient ascent / input optimization)** 으로 업데이트하여 목표 물성으로 유도하는 접근을 제안. 추가적인 생성모델 학습 없이 “예측기만으로” 분자 생성이 가능하다고 주장. [https://doi.org/10.1038/s41467-025-59439-1] [archive/openalex/text/W4410193211.txt]
- **제약조건을 통한 ‘유효 분자’ 강제**: 무제약 input optimization은 무의미한 그래프를 만들 수 있으므로, (i) 인접행렬의 대칭/정수성(“sloped rounding”으로 미분가능성 확보) 및 (ii) **원자가(valence) 제한(>4 페널티 및 gradient 차단)** 등 화학 규칙을 강제하여 유효 분자만 생성되게 설계. [https://doi.org/10.1038/s41467-025-59439-1] [archive/openalex/text/W4410193211.txt]
- **타깃 물성 예시로 HOMO–LUMO gap(에너지 갭) 타깃팅**을 제시(DFT로 검증), 목표 물성 도달률이 SOTA 생성모델과 동급/상회 + 다양성(diversity) 우수 주장. OLED 발광재료 탐색에서 자주 쓰는 **전자구조 지표(갭 등)** 를 “역설계(inverse design)”로 다루는 전형적 워크플로 사례로 활용 가능. [https://doi.org/10.1038/s41467-025-59439-1] [archive/openalex/text/W4410193211.txt]

### B. *Quantum-AI Synergy and the Framework for Assessing Quantum Advantage* (JPAIR, 2025)
- **“표준화된 양자 적합성/우위 평가 프레임워크의 부재”를 문제로 명시**: 기업들이 어떤 문제가 양자 가속에 적합한지 불명확한 상태에서 투자한다는 “의사결정 프레임워크 갭”을 지적. [https://doi.org/10.63721/25jpair0118] [archive/openalex/text/W4417018335.txt]
- **양자 우위 평가를 위한 통합 프레임워크 제안**: 문제 특성화(problem characterization)–자원 추정(resource estimation)–양자 우위 판단(advantage assessment)–알고리즘 패러다임 선택을 결합한 방법론을 “통합 의사결정 도구”로 제시했다고 주장. (화학/최적화/ML/시뮬레이션 등 도메인에 적용 가능하다고 서술) [https://doi.org/10.63721/25jpair0118] [archive/openalex/text/W4417018335.txt]
- (주의) 본 문헌은 OLED 특이 사례가 아니라 “Quantum-AI 일반론 + 사례 나열” 성격이 강하므로, OLED 발광재료 분야에 적용할 때는 **‘평가 틀’로만 차용**하는 것이 안전. [https://doi.org/10.63721/25jpair0118] [archive/openalex/text/W4417018335.txt]

### C. *Exploring quantum materials and applications: a review* (Journal of Materials Science: Materials in Engineering, 2025)
- **‘quantum materials(QMs)’ 중심의 리뷰**: 양자구속, 강상관, 위상/대칭 등 “양자재료”의 성질/유형/응용을 개관. OLED 발광재료 설계에 직접 연결되는 “양자컴퓨팅 기반 분자/재료 탐색”과는 결이 다를 수 있어 **용어 혼선 정리** 근거로 적합. [https://doi.org/10.1186/s40712-024-00202-7] [archive/openalex/text/W4406477905.txt]
- QDs(quantum dots) 관련 노벨상 언급 등 디스플레이/소재 맥락이 일부 있으나, “OLED 발광 유기분자/착물”의 양자계산 적용과는 별개 축. [https://doi.org/10.1186/s40712-024-00202-7] [archive/openalex/text/W4406477905.txt]

### D. *Forecasting the future: From quantum chips to neuromorphic engineering and bio-integrated processors* (Book chapter, 2025)
- “Beyond Moore’s Law” 맥락에서 양자컴퓨팅/뉴로모픽 등 비전형 컴퓨팅 패러다임을 전망하는 서술(개론/로드맵 성격). OLED 직접 근거로 쓰기보다는 “산업/기술 배경” 보조 정도가 적절. [https://doi.org/10.70593/978-93-49910-47-8_12] [archive/openalex/text/W4410446803.txt]

### E. *Electrospinning vs Fluorescent Organic Nano-Dots…* (2025)
- organoluminophores에서 ES/FON 비교 리뷰로, OLED 발광재료×양자컴퓨팅 동향과는 직접 관련이 약함(참고로 OLED/TADF 등의 약어 정의는 포함). [https://doi.org/10.1007/s10904-024-03567-6] [archive/openalex/text/W4406330631.txt]

---

## 2) 웹/업계 자료(supporting) — OLED×양자컴퓨팅 “직접 언급” 근거

### A. IBM Research Blog (OLED 응용을 명시)
- Mitsubishi Chemical(IBM Quantum Innovation Center at Keio Univ. 멤버) 및 Keio University/JSR 협업 맥락에서, **NISQ 잡음/제약을 다루기 위한 error mitigation 및 “novel quantum algorithms”** 를 언급. [https://research.ibm.com/blog/quantum-for-oled] [archive/tavily_search.jsonl]
- **arXiv 프리프린트 제목을 명시**: “Applications of Quantum Computing for Investigations of Electronic Transitions in Phenylsulfonyl-carbazole TADF Emitters”에서 **OLED에 쓰일 수 있는 산업용 화합물의 excited states(여기상태) 계산**을 다뤘다고 서술. [https://research.ibm.com/blog/quantum-for-oled] [archive/tavily_search.jsonl]
- 대상 분자로 **phenylsulfonyl-carbazole(PSPCz) 계열** 및 TADF 맥락, 그리고 TADF가 100% internal quantum efficiency 잠재력을 가진다는 일반 설명 포함. [https://research.ibm.com/blog/quantum-for-oled] [archive/tavily_search.jsonl]

### B. Mitsubishi Chemical 관련 PDF(회사/허브 문서; npj Computational Materials 게재 주장)
- IBM Quantum Network Hub at Keio University의 공동 프로젝트가 **npj Computational Materials** 에 게재되었다고 하며, **TADF emitters의 excited states 계산** 및 **오차완화(error mitigation)로 계산 정확도 개선**을 주장. [https://www.mcgc.com/english/news_mcc/2021/__icsFiles/afieldfile/2021/05/26/qhubeng.pdf] [archive/tavily_search.jsonl]
- 기술적으로 **qEOM-VQE 및 VQD 알고리즘을 사용해 TADF 재료의 여기상태 에너지 예측**이 목표라고 명시. [https://www.mcgc.com/english/news_mcc/2021/__icsFiles/afieldfile/2021/05/26/qhubeng.pdf] [archive/tavily_search.jsonl]
- (주의) 이 PDF 자체는 “논문 원문”이 아니라 보도/소개 성격의 2차 자료로 보이며, 핵심은 언급된 **npj 원문을 1차 문헌으로 확보**하는 것.

### C. Nature (npj Computational Materials) 논문 페이지(1차 논문 URL 존재; 아카이브에는 원문 미다운로드)
- OLED 디스플레이용 phenylsulfonyl-carbazole TADF emitters 3종에 대해 **qEOM‑VQE 및 VQD로 excited states를 조사**(시뮬레이터 + IBM Quantum devices)했다고 결론에서 요약. [https://www.nature.com/articles/s41524-021-00540-6] [archive/tavily_search.jsonl]
- **ΔE_ST(S1–T1 에너지 갭) 예측이 실험과 양립**하며, 구조 변화와 여기상태 에너지 관계 이해에 도움이 된다고 서술. [https://www.nature.com/articles/s41524-021-00540-6] [archive/tavily_search.jsonl]

### D. OLED‑Info 기사(산업 동향 “서술”)
- Mitsubishi Chemical이 **OLED emitter 소재 개발을 위해 QAOA를 개발**해왔고, 잡음 누적에 따른 정확도 문제가 있었다는 취지로 서술(“circuit compression” 언급). [https://www.oled-info.com/mitsubishi-chemcial-deloitte-tohmatsu-and-classiq-manage-dramatically-improve] [archive/tavily_search.jsonl]
- Keio University×Mitsubishi Chemical 협업에서 **고전 계산+양자 계산+ML을 결합한 워크플로**를 서술하며, 예시로 deuterated Alq3 유도체를 언급. [https://www.oled-info.com/researchers-combine-classical-computing-quantum-computing-discover-promising] [archive/tavily_search.jsonl]
- (주의) OLED‑Info는 유료/업계 뉴스 성격이므로, 핵심 주장(알고리즘/성과)은 **논문/공식 발표로 교차검증 필요**.

### E. arXiv HTML (양자우위/자원 스케일 주장; OLED phosphorescent emitters 벤치마크)
- iQCC를 VQE 계열 알고리즘으로 설명하고, **Ir(III)/Pt(II) phosphorescent complexes(OLED 소재) 14종**의 excited-state 에너지를 벤치마크로 사용했다고 서술. [https://arxiv.org/html/2512.13657v1] [archive/tavily_search.jsonl]
- iQCC를 OLED phosphorescent emitters 소재 탐색 프로세스에 활용할 가능성을 언급. [https://arxiv.org/html/2512.13657v1] [archive/tavily_search.jsonl]
- (참고) LinkedIn 게시물은 “협업/정확도/자원(논리 큐비트 등) 주장”이 있으나, 1차 문헌으로는 arXiv/논문을 우선시하는 것이 적절. [https://www.linkedin.com/posts/scott-genin-943a9118_towards-quantum-advantage-in-chemistry-activity-7413657675890122752-JrEs] [archive/tavily_search.jsonl]

---

## 3) 기업(삼성디스플레이/LG/UDC) 공개정보 — “양자컴퓨팅 기반 OLED 발광재료 개발” 직접 근거의 한계

### A. Samsung Display / Samsung Newsroom (QD‑OLED 중심)
- Samsung Display의 QD‑OLED 구조/특성(반사 저감, blue EL self‑emission 등)을 설명하는 제품/기술 소개는 있으나, **양자컴퓨팅 기반 발광재료 탐색 적용**을 직접 입증하는 내용은 확인되지 않음(현 아카이브 범위). [https://www.samsungdisplay.com/eng/tech/quantum-dot.jsp] [archive/tavily_search.jsonl]
- Samsung 뉴스룸의 “quantum dot” 관련 글은 QD 소재/필름/무카드뮴 등의 디스플레이 소재 혁신 서술이며, **‘quantum’은 quantum dot 의미**로 사용(quantum computing과 구분 필요). [https://news.samsung.com/ca/real-quantum-dot-guide-samsungs-innovations-redefine-picture-quality-standards] [archive/tavily_search.jsonl]

### B. LG Corp 보도자료(재료 내재화/공급망)
- LG Display–LG Chem이 p‑Dopant를 공동 개발(협업 기간/적용 계획 등)을 공개했으나, **양자컴퓨팅 활용 근거는 없음**. [https://www.lgcorp.com/media/release/26853] [archive/tavily_search.jsonl]

### C. UDC(Universal Display Corporation) IR/보도자료
- Merck KGaA의 OLED 특허 자산 인수(110+ 특허패밀리 등) 등은 **소재/IP 전략** 근거이나, 양자컴퓨팅 적용을 직접 말하지는 않음. [https://ir.oled.com/newsroom/press-releases/press-release-details/2025/Universal-Display-Corporation-to-Acquire-Emissive-OLED-Patent-Assets-from-Merck-KGaA-Darmstadt-Germany/default.aspx] [archive/tavily_search.jsonl]

---

## 4) 아카이브 커버리지/갭(근거 공백) — 로그 기반 사실

- 본 작업 설정상 **arXiv IDs = 0**으로 수집되었고, 실제 핵심 arXiv/npj 논문은 “웹 검색 결과에 URL로만 존재”함. [archive/20260110_qc-oled-index.md], [archive/_log.txt]
- OpenAlex PDF 다운로드가 Wiley/ASME/MDPI 등에서 **403 Forbidden으로 실패**한 기록이 있음(따라서 OLED 직접 관련 1차 문헌이 빠졌을 가능성). [archive/_log.txt]
- 결과적으로 OLED×QC의 “핵심 1차 연구”로 보이는 npj 논문은 **OpenAlex 텍스트/PDF로 확보되어 있지 않고**, 웹 링크(예: Nature 페이지) 및 IBM/기업 문서 인용에 의존하는 상태. [https://www.nature.com/articles/s41524-021-00540-6] [archive/tavily_search.jsonl], [https://research.ibm.com/blog/quantum-for-oled] [archive/tavily_search.jsonl], [archive/_log.txt]