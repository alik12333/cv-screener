# Extraction eval — 2026-08-18

CVs compared: 62/62 (0 failed extraction entirely)

## Per-field accuracy (exact match, case/whitespace-insensitive)
- full_name: 100.0% (62/62)
- email: 100.0% (62/62)
- phone: 100.0% (62/62)
- location: 100.0% (62/62)
- current_title: 100.0% (62/62)
- notice_period: 100.0% (62/62)
- salary_expectation: 98.4% (61/62)
- total_years_experience: 74.2% (46/62)

## Fuzzy fields
- skills (set F1): 1.000 average
- personal_statement (text similarity ratio): 1.000 average, 62/62 CVs >= 0.85 similarity

## Nested fields (per-entry, order-aligned)
- employment (employer+title match): 100.0% (118/118)
- education (institution+qualification match): 100.0% (62/62)

## By CV layout (average per-CV score across all fields above)
- classic: 0.996 (22 CVs)
- terse: 0.981 (22 CVs)
- header_heavy: 0.949 (18 CVs)

## Excluded from scoring
- right_to_work: never appears in the rendered CV text in any layout (confirmed across all ground truth files). Scoring it would reward a lucky default guess rather than genuine extraction. See docs/LEARNING.md Day 2.