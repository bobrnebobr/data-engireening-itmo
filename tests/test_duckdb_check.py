import csv
import tempfile
import unittest
from pathlib import Path

import duckdb

from duckdb_analysis.check import calculate, compare_table


class DuckDBCheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.connection = duckdb.connect(config={"threads": 1})
        self.addCleanup(self.connection.close)

    def source(self, rows):
        path = self.directory / "input.csv"
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["vacancy_id", "name", "key_skills", "salary_from", "salary_to", "currency", "gross", "area"])
            writer.writerows([list(row) + [""] * (8 - len(row)) for row in rows])
        return str(path)

    def test_sql_filter_deduplication_unicode_and_combinations(self):
        source = self.source([
            [1, "АНАЛИТИК", " Python ; SQL;python; Git; \t "],
            [2, "ANALYſT", "STRASSE;Straße; Σ;ς; \u00a0"],
            [3, "Developer", "SQL;Rust"],
            [4, "Аналитик", "SQL"],
            [5, "Analyst", ""],
            [4, "Аналитик", "SQL"],
        ])
        calculate(self.connection, source)
        self.assertEqual(dict(self.connection.execute("SELECT * FROM singles").fetchall()),
                         {"git": 1, "python": 1, "sql": 3, "strasse": 1, "σ": 1})
        self.assertEqual(set(self.connection.execute("SELECT * FROM pairs").fetchall()), {
            ("git", "python", 1), ("git", "sql", 1), ("python", "sql", 1), ("strasse", "σ", 1),
        })
        self.assertEqual(self.connection.execute("SELECT * FROM triples").fetchall(), [("git", "python", "sql", 1)])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM analyst_vacancies").fetchone()[0], 5)

    def compare_singles(self, rows):
        path = self.directory / "singles.csv"
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["skill", "count"])
            writer.writerows(rows)
        return compare_table(self.connection, "singles", str(path))

    def test_comparison_checks_values_not_only_number_of_rows(self):
        calculate(self.connection, self.source([[1, "Analyst", "SQL;Python"], [2, "Analyst", "SQL"]]))
        result = self.compare_singles([["sql", 1], ["python", 2]])
        self.assertFalse(result["matches"])
        self.assertEqual(result["sql_rows"], result["mapreduce_rows"])
        self.assertEqual(result["sql_only_rows"], 2)
        self.assertEqual(result["mapreduce_only_rows"], 2)

    def test_comparison_detects_duplicate_rows(self):
        calculate(self.connection, self.source([[1, "Analyst", "SQL"]]))
        result = self.compare_singles([["sql", 1], ["sql", 1]])
        self.assertFalse(result["matches"])
        self.assertEqual(result["mapreduce_only_rows"], 1)

    def test_comparison_accepts_reordered_rows(self):
        calculate(self.connection, self.source([[1, "Analyst", "SQL;Python"], [2, "Analyst", "SQL"]]))
        self.assertTrue(self.compare_singles([["sql", 2], ["python", 1]])["matches"])
        # DuckDB 2 requires prior execute results to be fully consumed before export.
        path = self.directory / "export.csv"
        self.connection.sql("SELECT * FROM singles ORDER BY skill").write_csv(str(path), header=True)
        with path.open(encoding="utf-8", newline="") as file:
            self.assertEqual(list(csv.reader(file)), [["skill", "count"], ["python", "1"], ["sql", "2"]])

    def test_comparison_handles_escaped_quotes_in_pairs(self):
        calculate(self.connection, self.source([[1, "Analyst", '1с программирование;1с:профессионал"']]))
        path = self.directory / "pairs.csv"
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["skill_1", "skill_2", "count"])
            writer.writerow(["1с программирование", '1с:профессионал"', 1])
        self.assertTrue(compare_table(self.connection, "pairs", str(path))["matches"])

    def test_empty_source_and_results(self):
        calculate(self.connection, self.source([]))
        for name in ["singles", "pairs", "triples"]:
            self.assertEqual(self.connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0], 0)
        self.assertTrue(self.compare_singles([])["matches"])


if __name__ == "__main__":
    unittest.main()
