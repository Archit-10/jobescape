from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

import config as C

Level = Literal["intern", "entry", "mid", "senior", "lead", "executive", "any"]
JobType = Literal["fulltime", "parttime", "internship", "contract"]
WorkMode = Literal["any", "remote", "onsite"]
TitleMatch = Literal["off", "any", "all"]


def _clean_list(v: List[str], lower: bool = True, cap: int = 50) -> List[str]:
    out = []
    for x in v:
        x = x.strip()
        x = x.lower() if lower else x
        if x and x not in out:
            out.append(x)
    return out[:cap]


class ScrapeRequest(BaseModel):
    """Every field except `search_term` is optional. Nothing is pre-filtered for any profession."""

    # --- what to search ---
    search_term: str = Field(..., min_length=2, max_length=100, examples=["Data Analyst"])
    extra_search_terms: List[str] = Field(default_factory=list, max_length=4,
                                          description="Run extra queries, e.g. 'Business Analyst'.")
    # --- where ---
    countries: List[str] = Field(default_factory=lambda: [C.WORLDWIDE_KEY],
                                 description="Country names, 'remote' or 'worldwide'.")
    cities: List[str] = Field(default_factory=list, description="Free text like 'Bangalore, India'.")
    # --- which platforms (default: all) ---
    sites: List[str] = Field(default_factory=lambda: list(C.ALL_SITES))
    # --- job filters ---
    hours_old: Optional[int] = Field(72, ge=1, le=24 * 90, description="null = any age")
    work_mode: WorkMode = "any"
    job_types: List[JobType] = Field(default_factory=list)
    easy_apply: bool = False
    experience_levels: List[Level] = Field(default_factory=list)
    max_experience_years: Optional[int] = Field(None, ge=0, le=40)
    min_salary_annual: Optional[float] = Field(None, ge=0)
    salary_currency: Optional[str] = Field(None, max_length=3, description="e.g. USD; compares same-currency only")
    require_salary: bool = False
    # --- keyword controls (all optional) ---
    must_include_any: List[str] = Field(default_factory=list)
    must_include_all: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)
    boost_keywords: List[str] = Field(default_factory=list, description="Rank higher, never remove.")
    title_match: TitleMatch = "off"
    company_include: List[str] = Field(default_factory=list)
    company_exclude: List[str] = Field(default_factory=list)
    # --- personalisation (replaces the old hardcoded Java gap list) ---
    my_skills: List[str] = Field(default_factory=list, description="Your skills, for match % and gaps.")
    # --- output ---
    results_per_site: int = Field(30, ge=1, le=C.MAX_RESULTS_PER_SITE)
    top_n: int = Field(100, ge=1, le=1000)
    fetch_full_description: bool = Field(True, description="Slower on LinkedIn, but far better filtering.")

    @field_validator("sites")
    @classmethod
    def _sites(cls, v):
        v = _clean_list(v)
        bad = [s for s in v if s not in C.SITE_RULES]
        if bad:
            raise ValueError(f"Unsupported site(s): {bad}. Choose from {list(C.SITE_RULES)}")
        if not v:
            raise ValueError("Select at least one site.")
        return v

    @field_validator("countries")
    @classmethod
    def _countries(cls, v):
        return _clean_list(v)

    @field_validator("extra_search_terms")
    @classmethod
    def _terms(cls, v):
        return _clean_list(v, lower=False, cap=4)

    @field_validator("cities")
    @classmethod
    def _cities(cls, v):
        return _clean_list(v, lower=False, cap=20)

    @field_validator("search_term")
    @classmethod
    def _term(cls, v):
        return v.strip()

    @field_validator("must_include_any", "must_include_all", "exclude_keywords", "boost_keywords",
                     "company_include", "company_exclude", "my_skills")
    @classmethod
    def _lists(cls, v):
        return _clean_list(v)
