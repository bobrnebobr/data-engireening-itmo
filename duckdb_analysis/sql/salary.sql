CREATE OR REPLACE TEMP TABLE salary_skill_rows AS
SELECT s.row_id, v.pay_basis, v.salary, s.skill
FROM vacancy_skills s JOIN salary_vacancies v USING (row_id);

-- A combination with global frequency below the threshold cannot have enough salaries.
CREATE OR REPLACE TEMP TABLE salary_pair_rows AS
SELECT a.row_id, a.pay_basis, a.salary, a.skill AS skill_1, b.skill AS skill_2
FROM salary_skill_rows a
JOIN salary_skill_rows b ON a.row_id = b.row_id AND a.skill < b.skill
JOIN pairs p ON p.skill_1 = a.skill AND p.skill_2 = b.skill
WHERE p.count >= $min_samples;

CREATE OR REPLACE TEMP TABLE salary_observations AS
SELECT row_id, pay_basis, salary, [skill] AS skills FROM salary_skill_rows
UNION ALL
SELECT row_id, pay_basis, salary, [skill_1, skill_2] FROM salary_pair_rows
UNION ALL
SELECT p.row_id, p.pay_basis, p.salary, [p.skill_1, p.skill_2, c.skill]
FROM salary_pair_rows p
JOIN salary_skill_rows c ON p.row_id = c.row_id AND p.skill_2 < c.skill
JOIN triples t ON t.skill_1 = p.skill_1 AND t.skill_2 = p.skill_2 AND t.skill_3 = c.skill
WHERE t.count >= $min_samples;

CREATE OR REPLACE TEMP TABLE salary_statistics AS
SELECT skills, pay_basis, count(*) AS salary_samples, median(salary) AS median_salary
FROM salary_observations GROUP BY skills, pay_basis;

CREATE OR REPLACE TEMP TABLE global_combinations AS
SELECT [skill_1, skill_2] AS skills, count AS frequency FROM pairs WHERE count >= $min_samples
UNION ALL
SELECT [skill_1, skill_2, skill_3], count FROM triples WHERE count >= $min_samples;

-- The most frequent individual skill is determined on ALL analyst vacancies.
CREATE OR REPLACE TEMP TABLE dominant_single AS
SELECT c.skills, s.skill, s.count AS frequency
FROM global_combinations c JOIN singles s ON list_contains(c.skills, s.skill)
QUALIFY row_number() OVER (PARTITION BY c.skills ORDER BY s.count DESC, s.skill) = 1;

-- Pair: baseline = most frequent skill. Triple: baseline = most frequent contained pair.
-- Lexicographic ordering breaks ties deterministically.
CREATE OR REPLACE TEMP TABLE combination_baselines AS
SELECT skills, [skill] AS baseline_skills, frequency AS baseline_frequency
FROM dominant_single WHERE len(skills) = 2
UNION ALL
SELECT c.skills, [p.skill_1, p.skill_2], p.count
FROM global_combinations c
JOIN pairs p ON list_contains(c.skills, p.skill_1) AND list_contains(c.skills, p.skill_2)
WHERE len(c.skills) = 3
QUALIFY row_number() OVER (
    PARTITION BY c.skills ORDER BY p.count DESC, p.skill_1, p.skill_2
) = 1;

CREATE OR REPLACE TEMP TABLE salary_effects AS
SELECT len(s.skills) AS arity, s.skills, s.pay_basis, g.frequency,
       s.salary_samples, s.median_salary,
       b.baseline_skills, b.baseline_frequency,
       base.salary_samples AS baseline_salary_samples,
       base.median_salary AS baseline_median_salary,
       s.median_salary - base.median_salary AS delta_rub,
       100 * (s.median_salary / base.median_salary - 1) AS delta_percent,
       d.skill AS baseline_single_skill, d.frequency AS baseline_single_frequency,
       anchor.salary_samples AS baseline_single_salary_samples,
       anchor.median_salary AS baseline_single_median_salary,
       s.median_salary - anchor.median_salary AS delta_from_single_rub,
       100 * (s.median_salary / anchor.median_salary - 1) AS delta_from_single_percent
FROM salary_statistics s
JOIN global_combinations g USING (skills)
JOIN combination_baselines b USING (skills)
JOIN salary_statistics base ON base.skills = b.baseline_skills AND base.pay_basis = s.pay_basis
JOIN dominant_single d ON d.skills = s.skills
JOIN salary_statistics anchor ON anchor.skills = [d.skill] AND anchor.pay_basis = s.pay_basis
WHERE s.salary_samples >= $min_samples AND base.salary_samples >= $min_samples;

CREATE OR REPLACE TEMP VIEW salary_effects_flat AS
SELECT arity, skills[1] AS skill_1, skills[2] AS skill_2, skills[3] AS skill_3,
       pay_basis, frequency, salary_samples, median_salary,
       array_to_string(baseline_skills, ' + ') AS baseline_skills,
       baseline_frequency, baseline_salary_samples, baseline_median_salary,
       delta_rub, delta_percent, baseline_single_skill, baseline_single_frequency,
       baseline_single_salary_samples, baseline_single_median_salary,
       delta_from_single_rub, delta_from_single_percent
FROM salary_effects;
