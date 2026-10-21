CREATE OR REPLACE TEMP TABLE singles AS
SELECT skill, count(*)::BIGINT AS count
FROM vacancy_skills
GROUP BY skill;

CREATE OR REPLACE TEMP TABLE pairs AS
SELECT a.skill AS skill_1, b.skill AS skill_2, count(*)::BIGINT AS count
FROM vacancy_skills a
JOIN vacancy_skills b ON a.row_id = b.row_id AND a.skill < b.skill
GROUP BY a.skill, b.skill;

CREATE OR REPLACE TEMP TABLE triples AS
SELECT a.skill AS skill_1, b.skill AS skill_2, c.skill AS skill_3,
       count(*)::BIGINT AS count
FROM vacancy_skills a
JOIN vacancy_skills b ON a.row_id = b.row_id AND a.skill < b.skill
JOIN vacancy_skills c ON b.row_id = c.row_id AND b.skill < c.skill
GROUP BY a.skill, b.skill, c.skill;
