import csv
import tempfile
import unittest
from pathlib import Path

import duckdb

from duckdb_analysis.check import prepare_data
from duckdb_analysis.regions import DEFAULT_REGIONS, calculate_regions


class RegionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)/'source.csv'
        self.connection = duckdb.connect(config={'threads':1})
        self.addCleanup(self.connection.close)

    def run_rows(self, rows, minimum=1):
        with self.path.open('w',encoding='utf-8',newline='') as file:
            writer=csv.writer(file)
            writer.writerow(['vacancy_id','name','key_skills','salary_from','salary_to','currency','gross','area'])
            for n,(region,skills,salary,currency,gross) in enumerate(rows):
                writer.writerow([n,'Analyst',skills,salary,'',currency,gross,region])
        prepare_data(self.connection,str(self.path))
        calculate_regions(self.connection,DEFAULT_REGIONS,minimum)

    def test_city_medians_include_vacancies_without_skills(self):
        rows=[
            ('Москва','A;B;C',100,'RUR','false'),('Москва','A;B;C',300,'RUR','false'),
            ('Москва','A;B',50,'RUR','false'),('Москва','',40,'RUR','false'),
            ('Москва','A;B;C',1000,'USD','false'),
            ('Санкт-Петербург','A;B',500,'RUR','false'),('Санкт-Петербург','B',100,'RUR','false'),
            ('Санкт-Петербург','B','','',''),('Санкт-Петербург','B','','',''),
            ('Санкт-Петербург','B','','',''),('Санкт-Петербург','B;C',800,'RUR','true'),
            ('Екатеринбург','A;B;C',200,'RUR','false'),('Екатеринбург','A;B',50,'RUR','false'),
            ('Екатеринбург','',100,'RUR','false'),
        ]
        self.run_rows(rows)
        result=self.connection.execute("""SELECT vacancies,vacancies_with_skills,
            declared_salary_vacancies,ruble_salary_vacancies,net_salary_samples,net_median_salary
            FROM regional_overview WHERE region='Москва'""").fetchall()[0]
        self.assertEqual(result,(5,4,5,4,4,75.0))
        medians=dict(self.connection.execute('SELECT region,net_median_salary FROM regional_overview').fetchall())
        self.assertEqual(medians,{'Москва':75.0,'Санкт-Петербург':300.0,'Екатеринбург':100.0})
        share=self.connection.execute("SELECT frequency,share_percent FROM regional_frequencies WHERE region='Москва' AND arity=3").fetchall()[0]
        self.assertEqual(share,(3,60.0))
        baseline=self.connection.execute("""SELECT baseline_skills,baseline_median_salary,median_salary
            FROM regional_salary_effects WHERE region='Санкт-Петербург'
            AND skill_1='a' AND skill_2='b' AND arity=2 AND pay_basis='net'""").fetchall()[0]
        self.assertEqual(baseline,('b',300.0,500.0))
        matrix=dict(self.connection.execute("SELECT region,frequency FROM regional_frequency_comparison WHERE arity=1 AND skill_1='a'").fetchall())
        self.assertEqual(matrix,{'Москва':4,'Санкт-Петербург':1,'Екатеринбург':2})

    def test_frequency_triples_kept_when_salary_sample_is_small(self):
        self.run_rows([
            ('Москва','A;B;C',100,'RUR','false'),('Москва','A;B;C',300,'RUR','false'),
            ('Екатеринбург','A;B;C',200,'RUR','false'),('Екатеринбург','',100,'RUR','false'),
        ],minimum=2)
        self.assertEqual(self.connection.execute("SELECT frequency,share_percent FROM regional_frequencies WHERE region='Екатеринбург' AND arity=3").fetchall(),[(1,50.0)])
        self.assertEqual(self.connection.execute("SELECT count(*) FROM regional_salary_effects WHERE region='Екатеринбург'").fetchall()[0][0],0)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM regional_salary_effects WHERE region='Москва' AND arity=3").fetchall()[0][0],1)

    def test_exact_city_filter_aliases_and_empty_city(self):
        self.run_rows([
            (' ЕКАТЕРИНБУРГ ','Excel;MS Excel;PowerBI;power bi',100,'RUR','false'),
            ('Московская область','A;B;C',1000,'RUR','false'),
            ('Москва и Московская область','A',1000,'RUR','false'),
        ])
        counts=dict(self.connection.execute('SELECT region,vacancies FROM regional_overview').fetchall())
        self.assertEqual(counts,{'Москва':0,'Санкт-Петербург':0,'Екатеринбург':1})
        self.assertEqual(self.connection.execute('SELECT count(*) FROM regional_frequencies WHERE arity=3').fetchall()[0][0],0)
        pair=self.connection.execute("SELECT skill_1,skill_2,frequency FROM regional_frequencies WHERE arity=2").fetchall()
        self.assertEqual(pair,[('ms excel','power bi',1)])
        empty=self.connection.execute("SELECT frequency,share_percent FROM regional_frequency_comparison WHERE region='Москва'").fetchall()
        self.assertTrue(empty)
        self.assertTrue(all(n==0 and share is None for n,share in empty))

    def test_invalid_region_selection_is_rejected(self):
        for regions in [[],['Москва','Москва','Екатеринбург'],['Москва',' мОСКВА ','Екатеринбург'],['Москва','','Екатеринбург']]:
            with self.assertRaises(ValueError):calculate_regions(self.connection,regions)
        with self.assertRaises(ValueError):calculate_regions(self.connection,DEFAULT_REGIONS,0)


if __name__=='__main__':
    unittest.main()
