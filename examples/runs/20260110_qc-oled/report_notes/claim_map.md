Claim | Evidence | Strength | Flags
--- | --- | --- | ---
**Rajat Kumar Goyal et al., “Exploring quantum materials and applications: a review” (Journal of Materials Science: Materials in Engineering, 2025)** | (none) | none | no_evidence
핵심 주장/범위: *quantum materials (QMs)*를 “quantum confinement, strong electronic correlations, topology, symmetry” 등 **양자효과가 거시 물성으로 나타나는 재료**로 정의하고 유형/응용을 개괄함. | ./archive/openalex/text/W4406477905.txt; ./archive/openalex/text/W4406477905.txt; /archive/openalex/text/W4406477905.txt | high | -
OLED 관점 관련성: **양자컴퓨팅 기반 분자/여기상태 계산(OLED 발광재료)**이 아니라, “양자재료(quantum materials)” 중심의 리뷰라서 *QC×OLED* 직접 근거로는 약함. 다만 “quantum dots(QDs)” 등 디스플레이 소재 언급이 있어 **‘quantum’ 용어 혼동(QD vs quantum computing)** 리스크를 보여주는 사례로 활용 가능. “The Nobel Prize in Chemistry for 2023 recognizes… quantum dots (QDs)… Today, QDs illuminate screens in QLED technology…” (원문 PDF: https://jmsg.springeropen.com/counter/pdf/10.1186/s40712-024-00202-7) | ./archive/openalex/text/W4406477905.txt; https://jmsg.springeropen.com/counter/pdf/10.1186/s40712-024-00202-7; ./archive/openalex/text/W4406477905.txt (+1 more) | high | -
**Amit Singh, “Quantum-AI Synergy and the Framework for Assessing Quantum Advantage” (J of Pioneering Artificial Intelligence Research, 2025)** | (none) | none | no_evidence
핵심 주장: AI-quantum 상호보완(오류정정/회로최적화 vs QML)과 더불어 **“quantum advantage 평가를 위한 통합 프레임워크”**를 제시한다고 주장. “No standardized methodology exists… The framework consolidates criteria… into a unified decision-making tool…” | ./archive/openalex/text/W4417018335.txt; ./archive/openalex/text/W4417018335.txt; /archive/openalex/text/W4417018335.txt | high | -
OLED 관점 관련성: OLED 직접 내용은 없으나, **산업 적용 간극/‘양자 이점’ 주장 검증 프레임**(문제 특성화→자원 추정→QA 평가→알고리즘 선택)을 “방법론 섹션” 근거로 쓸 수 있음(단, 저널/근거 강도 자체는 별도 평가 필요). (원문 DOI: https://doi.org/10.63721/25jpair0118, 아카이브 텍스트: ) | ./archive/openalex/text/W4417018335.txt; https://doi.org/10.63721/25jpair0118; ./archive/openalex/text/W4417018335.txt (+1 more) | high | -
-- | (none) | none | no_evidence
**IBM Research Blog, “Unlocking today’s quantum computers for OLED applications”** | (none) | none | no_evidence
주장: Mitsubishi Chemical(Keio IBM Quantum Innovation Center 참여) 등과 함께 **오류 완화(error mitigation)·새 양자 알고리즘**을 통해 OLED 후보 물질의 **여기상태(excited states)/전자전이**를 계산하는 접근을 소개. “we… describe quantum computations of the ‘excited states’… of industrial chemical compounds…” | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
OLED 물성 연결: PSPCz(phenylsulfonyl-carbazole) 계열을 **TADF emitters** 후보로 언급하고, TADF가 “100 percent internal quantum efficiency” 잠재력을 갖는다는 설명을 포함. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
원문 URL: https://research.ibm.com/blog/quantum-for-oled | https://research.ibm.com/blog/quantum-for-oled | low | -
**Mitsubishi Chemical Group (PDF), “A Joint Paper on Prediction of Optical Properties of OLED Materials …” (2021)** | (none) | none | no_evidence
주장(보도자료 성격): npj Computational Materials 게재 연구로서 **TADF 여기상태 계산에 양자컴퓨터 적용**, NISQ 오류로 chemical accuracy 달성이 어렵다는 한계를 전제하면서 **qEOM-VQE, VQD**로 “excited states energies of TADF materials” 예측을 목표로 했다고 서술. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
원문 URL: https://www.mcgc.com/english/news_mcc/2021/__icsFiles/afieldfile/2021/05/26/qhubeng.pdf | https://www.mcgc.com/english/news_mcc/2021/__icsFiles/afieldfile/2021/05/26/qhubeng.pdf | high | -
**Nature(Scientific Reports 계열이 아니라 npj Computational Materials), “Applications of quantum computing for investigations of electronic transitions in phenylsulfonyl-carbazole TADF emitters” (2021)** | (none) | none | no_evidence
결론부 요지(검색 스니펫): qEOM‑VQE/VQD로 **TADF emitters의 S1/T1 및 ΔEST**를 다루며, 시뮬레이터에서 exact diagonalization과 일치 및 실험과 “good agreement”라고 서술. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
원문 URL: https://www.nature.com/articles/s41524-021-00540-6 | https://www.nature.com/articles/s41524-021-00540-6 | low | -
**arXiv HTML, “Towards Quantum Advantage in Chemistry” (arXiv:2512.13657v1, 2025-12)** | (none) | none | no_evidence
OLED 관련 직접 진술(스니펫): **Ir(III), Pt(II) phosphorescent OLED emitters**의 여기상태 에너지를 벤치마크로 삼고, iQCC를 VQE-type 알고리즘으로 설명. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
원문 URL: https://arxiv.org/html/2512.13657v1 | https://arxiv.org/html/2512.13657v1 | high | -
**OLED-Info (업계 매체) 2건** | (none) | none | no_evidence
1) “Mitsubishi Chemical, Deloitte Tohmatsu and Classiq manage to dramatically improve the OLED material discover efficiency of quantum computing” | (none) | none | no_evidence
주장: Mitsubishi Chemical이 **QAOA**를 OLED emitter materials 개발에 활용해왔고, 노이즈 누적이 정확도 한계였다는 서술. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
URL: https://www.oled-info.com/mitsubishi-chemcial-deloitte-tohmatsu-and-classiq-manage-dramatically-improve | https://www.oled-info.com/mitsubishi-chemcial-deloitte-tohmatsu-and-classiq-manage-dramatically-improve | low | -
2) “Researchers combine classical computing with quantum computing to discover promising OLED emitters” | (none) | none | no_evidence
주장: Keio Univ.–Mitsubishi Chemical 협력, **고전 QC(양자화학 계산)→ML 모델 학습→양자-고전 하이브리드 설계** 워크플로로 deuterated Alq3 유도체를 찾았다고 요약. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
URL: https://www.oled-info.com/researchers-combine-classical-computing-quantum-computing-discover-promising | https://www.oled-info.com/researchers-combine-classical-computing-quantum-computing-discover-promising | low | -
비고: 업계매체/게스트포스트는 1차 근거로 쓰기 어렵고 **supporting**으로 분리 권장. | (none) | none | no_evidence
**삼성디스플레이/삼성 뉴스룸: QD-OLED(quantum dot) 기술 소개(= quantum computing 아님)** | (none) | none | no_evidence
“QD-OLED”가 TFT/self-emitting + quantum dot film 구조라는 기술 소개. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
용어 혼동 리스크: 본 런의 “Samsung Display quantum computing…” 질의가 사실상 **quantum dot** 페이지로 회귀함(= QC 적용 증거 아님). | (none) | none | no_evidence
URL: https://www.samsungdisplay.com/eng/tech/quantum-dot.jsp  (및 Samsung Newsroom 다수: ) | ./archive/tavily_search.jsonl; https://www.samsungdisplay.com/eng/tech/quantum-dot.jsp; ./archive/tavily_search.jsonl (+1 more) | low | -
**LG Corp 공식 보도자료(재료 개발이지만 QC 아님)** | (none) | none | no_evidence
LG Display–LG Chem의 p‑Dopant 자립 개발(공급망/특허/탠덤 OLED 언급)로 **산업 동향 근거**는 되나 **양자컴퓨팅 적용 증거는 없음**. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
URL: https://www.lgcorp.com/media/release/26853 | https://www.lgcorp.com/media/release/26853 | low | -
**UDC(Universal Display Corporation) 공식 IR 보도자료(특허/공급 계약; QC 아님)** | (none) | none | no_evidence
Merck KGaA OLED 특허자산 인수(300+ patents, 110+ families) 등 **IP/공급망 중심의 산업 이벤트**. | ./archive/tavily_search.jsonl; ./archive/tavily_search.jsonl; /archive/tavily_search.jsonl | low | index_only
URL: https://ir.oled.com/newsroom/press-releases/press-release-details/2025/Universal-Display-Corporation-to-Acquire-Emissive-OLED-Patent-Assets-from-Merck-KGaA-Darmstadt-Germany/default.aspx | https://ir.oled.com/newsroom/press-releases/press-release-details/2025/Universal-Display-Corporation-to-Acquire-Emissive-OLED-Patent-Assets-from-Merck-KGaA-Darmstadt-Germany/default.aspx | low | -