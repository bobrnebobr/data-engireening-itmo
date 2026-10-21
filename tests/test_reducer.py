import unittest

from app.intermediate import IntermediateStore
from app.mapper import Mapper
from app.models import AggregatedCounts, Chunk, Vacancy
from app.reducer import Reducer


class ReducerTests(unittest.TestCase):
    def test_chunk_boundaries_do_not_change_counts(self):
        vacancies = [
            Vacancy(1, "Аналитик", ("Python", "SQL", "python")),
            Vacancy(2, "Data Analyst", ("Git", "SQL", "Python")),
            Vacancy(3, "Developer", ("Java",)),
            Vacancy(4, "Аналитик", ()),
        ]
        expected = AggregatedCounts(
            singles={"python": 2, "sql": 2, "git": 1},
            pairs={("python", "sql"): 2, ("git", "python"): 1, ("git", "sql"): 1},
            triples={("git", "python", "sql"): 1},
        )
        for size in [1, 2, 3, 4]:
            partials = (
                IntermediateStore.rows(Mapper.map(Chunk(start, vacancies[start:start + size])))
                for start in range(0, len(vacancies), size)
            )
            self.assertEqual(Reducer.reduce(partials), expected)

    def test_shared_keys_are_summed(self):
        partials = [[(("sql",), 2), (("python", "sql"), 3)], [(("sql",), 4)]]
        self.assertEqual(Reducer.reduce(partials).singles, {"sql": 6})
        self.assertEqual(Reducer.reduce(partials).pairs, {("python", "sql"): 3})

    def test_empty_results(self):
        self.assertEqual(Reducer.reduce([]), AggregatedCounts())
        self.assertEqual(Reducer.reduce([iter([]), iter([])]), AggregatedCounts())

    def test_invalid_intermediate_rows_rejected(self):
        for row in [((), 1), (("sql",), 0), (("sql", "python"), 1), (("sql", "sql"), 1)]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                Reducer.reduce([[row]])
