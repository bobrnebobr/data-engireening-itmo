from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, PositiveInt


@dataclass(frozen=True)
class Vacancy:
    vacancy_id: int
    name: str
    key_skills: tuple[str, ...]


class PairCount(BaseModel):
    skills: tuple[str, str]
    count: PositiveInt


class TripleCount(BaseModel):
    skills: tuple[str, str, str]
    count: PositiveInt


class Counts(BaseModel):
    singles: dict[str, PositiveInt] = Field(default_factory=dict)
    pairs: list[PairCount] = Field(default_factory=list)
    triples: list[TripleCount] = Field(default_factory=list)


@dataclass(frozen=True)
class Chunk:
    chunk_id: int
    vacancies: list[Vacancy]


@dataclass
class AggregatedCounts:
    singles: Counter[str] = field(default_factory=Counter)
    pairs: Counter[tuple[str, str]] = field(default_factory=Counter)
    triples: Counter[tuple[str, str, str]] = field(default_factory=Counter)
