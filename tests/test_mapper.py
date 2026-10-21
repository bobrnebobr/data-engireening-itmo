import unittest

from app.mapper import Mapper
from app.models import Chunk, Counts, Vacancy


class MapperTests(unittest.TestCase):
    def test_normalization_filter_and_frequencies(self):
        vacancies = [
            Vacancy(1, "Системный АНАЛИТИК", (" Python ", "SQL", "python", "", " ")),
            Vacancy(2, "Data Analyst", ("sql", "GIT", "PYTHON", "git")),
            Vacancy(3, "Разработчик", ("Java", "SQL")),
            Vacancy(4, "Аналитик", ()),
        ]
        original_skills = [vacancy.key_skills for vacancy in vacancies]
        result = Mapper.map(Chunk(0, vacancies))
        self.assertEqual(result.model_dump(mode="json"), {
            "singles": {"git": 1, "python": 2, "sql": 2},
            "pairs": [
                {"skills": ["git", "python"], "count": 1},
                {"skills": ["git", "sql"], "count": 1},
                {"skills": ["python", "sql"], "count": 2},
            ],
            "triples": [{"skills": ["git", "python", "sql"], "count": 1}],
        })
        self.assertEqual([vacancy.key_skills for vacancy in vacancies], original_skills)

    def test_empty_chunk(self):
        self.assertEqual(Mapper.map(Chunk(0, [])), Counts())

    def test_skill_order_does_not_change_result(self):
        first = Chunk(0, [Vacancy(1, "Аналитик", ("SQL", "Python", "Git"))])
        second = Chunk(0, [Vacancy(1, "Аналитик", ("git", "sql", "PYTHON"))])
        self.assertEqual(Mapper.map(first), Mapper.map(second))

    def test_four_distinct_skills_produce_all_combinations(self):
        result = Mapper.map(Chunk(0, [Vacancy(1, "Аналитик", ("A", "B", "C", "D"))]))
        self.assertEqual(len(result.singles), 4)
        self.assertEqual(len(result.pairs), 6)
        self.assertEqual(len(result.triples), 4)
        self.assertTrue(all(item.count == 1 for item in result.pairs + result.triples))


if __name__ == "__main__":
    unittest.main()
