import csv
import tempfile
import unittest
from pathlib import Path

import duckdb

from duckdb_analysis.check import calculate
from duckdb_analysis.salary import calculate_salary


class SalaryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'input.csv'
        self.connection = duckdb.connect(config={'threads': 1})
        self.addCleanup(self.connection.close)

    def run_rows(self, rows, minimum=2):
        with self.path.open('w', encoding='utf-8', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['vacancy_id','name','key_skills','salary_from','salary_to','currency','gross','area'])
            for number, (skills, low, high, currency, gross) in enumerate(rows):
                writer.writerow([number,'Analyst',skills,low,high,currency,gross,'Москва'])
        calculate(self.connection, str(self.path))
        calculate_salary(self.connection, minimum)

    def test_pair_and_triple_baselines_and_pay_basis_separation(self):
        self.run_rows([
            ('A;B;C',100,'','RUR','false'), ('A;B;C',300,'','RUR','false'),
            ('A;B',50,'','RUR','false'), ('A',40,'','RUR','false'),
            ('B;C',200,'','RUR','false'), ('B',10,'','RUR','false'),
            ('B',500,'','RUR','false'), ('A;B;C',1000,'','RUR','true'),
            ('A;C',10000,'','USD','false'), ('B',0,'','RUR','false'),
            ('A;B;C',3000,2000,'RUR','false'),
        ])
        result = self.connection.execute("""SELECT baseline_skills, baseline_median_salary,
            median_salary,delta_rub,baseline_single_skill,baseline_single_median_salary,
            delta_from_single_rub FROM salary_effects
            WHERE skills=['a','b','c'] AND pay_basis='net'""").fetchall()[0]
        self.assertEqual(result, (['a','b'],100.0,200.0,100.0,'b',150.0,50.0))
        pair = self.connection.execute("""SELECT baseline_skills,baseline_median_salary,delta_rub
            FROM salary_effects WHERE skills=['a','c'] AND pay_basis='net'""").fetchall()[0]
        self.assertEqual(pair, (['a'],75.0,125.0))
        self.assertEqual(self.connection.execute("SELECT count(*) FROM salary_effects WHERE pay_basis='gross'").fetchall()[0][0],0)
        self.assertEqual(self.connection.execute("SELECT median_salary FROM salary_statistics WHERE skills=['a','b','c'] AND pay_basis='gross'").fetchall()[0][0],1000)

    def test_baseline_frequency_uses_vacancies_without_salary(self):
        self.run_rows([
            ('A;B',100,'','RUR','false'), ('A',200,'','RUR','false'), ('A',300,'','RUR','false'),
            ('B','','','',''), ('B','','','',''), ('B','','','',''), ('B','','','',''),
        ], minimum=1)
        result=self.connection.execute("SELECT baseline_skills,baseline_frequency,baseline_median_salary FROM salary_effects WHERE skills=['a','b']").fetchall()[0]
        self.assertEqual(result, (['b'],5,100.0))

    def test_salary_proxy_and_invalid_bounds(self):
        self.run_rows([
            ('A;B',100,300,'RUR','false'), ('A;B',200,'','RUB','false'),
            ('A;B','',400,'RUR','false'), ('A;B','bad',100,'RUR','false'),
            ('A;B',0,100,'RUR','false'), ('A;B',500,100,'RUR','false'),
            ('A;B','NaN','','RUR','false'), ('A;B',10000,'','USD','false'),
            ('A;B',100,'','RUR',''),
        ])
        self.assertEqual(self.connection.execute("SELECT salary FROM salary_vacancies WHERE pay_basis='net' ORDER BY salary").fetchall(),[(200.0,),(200.0,),(400.0,)])
        self.assertEqual(self.connection.execute("SELECT median_salary FROM salary_statistics WHERE skills=['a','b'] AND pay_basis='net'").fetchall()[0][0],200)
        quality=dict(self.connection.execute('SELECT status,count(*) FROM salary_quality GROUP BY status').fetchall())
        self.assertEqual(quality,{'eligible':4,'invalid_salary_bounds':3,'inverted_range':1,'non_ruble_or_missing_currency':1})

    def test_aliases_do_not_create_duplicate_salary_observations(self):
        self.run_rows([('Docker;докер;DOCKER;Python;питон;пайтон',100,'','RUR','false')],minimum=1)
        self.assertEqual(self.connection.execute("SELECT skills,salary_samples FROM salary_statistics WHERE len(skills)=2").fetchall(),[(['docker','python'],1)])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM triples").fetchall()[0][0],0)

    def test_empty_salary_cohort_and_minimum(self):
        self.run_rows([('A;B','','','','')])
        self.assertEqual(self.connection.execute('SELECT count(*) FROM salary_effects').fetchall()[0][0],0)
        with self.assertRaises(ValueError): calculate_salary(self.connection,0)


if __name__ == '__main__':
    unittest.main()
