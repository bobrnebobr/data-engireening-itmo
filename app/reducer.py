from collections.abc import Iterable
from sys import intern

from app.models import AggregatedCounts


class Reducer:
    @staticmethod
    def reduce(
        partials: Iterable[Iterable[tuple[tuple[str, ...], int]]],
    ) -> AggregatedCounts:
        result = AggregatedCounts()
        for partial in partials:
            for skills, count in partial:
                if not 1 <= len(skills) <= 3 or count <= 0:
                    raise ValueError("Invalid intermediate frequency")
                if any(not skill for skill in skills) or tuple(sorted(set(skills))) != skills:
                    raise ValueError("Intermediate skills must be sorted and unique")
                # Reuse skill strings across keys instead of keeping a copy per JSON row.
                skills = tuple(intern(skill) for skill in skills)
                if len(skills) == 1:
                    result.singles[skills[0]] += count
                elif len(skills) == 2:
                    result.pairs[skills] += count
                else:
                    result.triples[skills] += count
        return result
