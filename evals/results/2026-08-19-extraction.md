# Extraction eval — 2026-08-19

CVs compared: 62/62 (0 failed extraction entirely)

## Per-field accuracy (exact match, case/whitespace-insensitive)
- full_name: 100.0% (62/62)
- email: 100.0% (62/62)
- phone: 100.0% (62/62)
- location: 100.0% (62/62)
- current_title: 100.0% (62/62)
- notice_period: 98.4% (61/62)
- salary_expectation: 96.8% (60/62)
- total_years_experience: 53.2% (33/62)

## Fuzzy fields
- skills (set F1): 0.992 average
- personal_statement (text similarity ratio): 1.000 average, 62/62 CVs >= 0.85 similarity

## Nested fields (per-entry, order-aligned)
- employment (employer+title match): 100.0% (149/149)
- education (institution+qualification match): 100.0% (67/67)

## By CV layout (average per-CV score across all fields above)
- classic: 0.981 (22 CVs)
- terse: 0.951 (22 CVs)
- header_heavy: 0.933 (18 CVs)

## Excluded from scoring
- right_to_work: never appears in the rendered CV text in any layout (confirmed across all ground truth files). Scoring it would reward a lucky default guess rather than genuine extraction. See docs/LEARNING.md Day 2.