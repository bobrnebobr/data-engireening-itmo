from collections import Counter
from itertools import combinations

from app.models import Chunk, Counts, PairCount, TripleCount
from app.skills import normalize_skill


class Mapper:
    @staticmethod
    def map(chunk: Chunk) -> Counts:
        singles: Counter[str] = Counter()
        pairs: Counter[tuple[str, str]] = Counter()
        triples: Counter[tuple[str, str, str]] = Counter()

        for vacancy in chunk.vacancies:
            name = vacancy.name.casefold()
            if "аналитик" not in name and "analyst" not in name:
                continue

            skills = sorted({
                normalize_skill(skill)
                for skill in vacancy.key_skills
                if skill.strip()
            })
            singles.update(skills)
            pairs.update(combinations(skills, 2))
            triples.update(combinations(skills, 3))

        return Counts(
            singles=dict(sorted(singles.items())),
            pairs=[
                PairCount(skills=skills, count=count)
                for skills, count in sorted(pairs.items())
            ],
            triples=[
                TripleCount(skills=skills, count=count)
                for skills, count in sorted(triples.items())
            ],
        )
