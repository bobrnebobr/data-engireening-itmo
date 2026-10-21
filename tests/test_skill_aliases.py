import unittest

from app.mapper import Mapper
from app.models import Chunk, Vacancy
from app.skills import normalize_skill


class SkillAliasTests(unittest.TestCase):
    def test_explicit_aliases_and_case_variants(self):
        for skill in ['докер','Docker','DOCKER',' докер ']:
            self.assertEqual(normalize_skill(skill),'docker')
        for skill in ['python','питон','пайтон','PYTHON','Питон']:
            self.assertEqual(normalize_skill(skill),'python')
        self.assertEqual(normalize_skill('Python3'),'python3')
        self.assertEqual(normalize_skill('Docker Compose'),'docker compose')

    def test_observed_product_aliases(self):
        counts=Mapper.map(Chunk(0,[Vacancy(1,'Analyst',('Excel','MS Excel','Microsoft Excel','PowerBI','MS Power BI','power bi'))]))
        self.assertEqual(counts.singles,{'ms excel':1,'power bi':1})
        self.assertEqual([(p.skills,p.count) for p in counts.pairs],[(('ms excel','power bi'),1)])
        self.assertEqual(counts.triples,[])
        for raw,canonical in [('Atlassian Jira','jira'),('Atlassian Confluence','confluence'),('Postgres','postgresql'),('JS','javascript'),('k8s','kubernetes')]:
            self.assertEqual(normalize_skill(raw),canonical)

    def test_deduplicates_after_alias_replacement(self):
        counts=Mapper.map(Chunk(0,[Vacancy(1,'Analyst',('Docker','докер','DOCKER','python','питон','пайтон'))]))
        self.assertEqual(counts.singles,{'docker':1,'python':1})
        self.assertEqual([(p.skills,p.count) for p in counts.pairs],[(('docker','python'),1)])
        self.assertEqual(counts.triples,[])
