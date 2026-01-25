# Report Workflow

## Stages
1. scout: cached
2. clarifier: skipped (no_questions)
3. template_adjust: ran
4. plan: cached
5. web: skipped (policy)
6. evidence: cached
7. plan_check: cached
8. writer: ran
9. quality: ran (iterations=1)

## Artifacts
### scout
- Scout notes: ./report_notes/scout_notes.md

### plan
- Plan update: ./report_notes/report_plan.md

### evidence
- Evidence notes: ./report_notes/evidence_notes.md
- Source triage: ./report_notes/source_triage.md
- Source index: ./report_notes/source_index.jsonl
- Claim map: ./report_notes/claim_map.md
- Gap report: ./report_notes/gap_finder.md

### quality
- Quality evaluations: ./report_notes/quality_evals.jsonl
- Quality pairwise: ./report_notes/quality_pairwise.jsonl
## Outputs
- Report overview: ./report/run_overview_report_full_1.md
- Report meta: ./report_notes/report_meta.json
- Report prompt copy: ./instruction/report_prompt_report_full_1.txt
- Template summary: ./report_notes/report_template.txt
