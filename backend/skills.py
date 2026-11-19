"""Cross-industry skill taxonomy. Entry format: "canonical|alias|alias". Extend freely."""
import re
from collections import Counter
from functools import lru_cache
from typing import Iterable, List, Set

SKILLS = {
    "Programming": [
        "java", "python", "javascript|js", "typescript", "c++", "c#", "golang", "rust", "kotlin",
        "swift", "php", "ruby", "scala", "sql", "bash|shell scripting", "matlab", "dart", "perl", "git|github",
    ],
    "Frontend": [
        "react|reactjs|react.js", "angular", "vue|vue.js|vuejs", "next.js|nextjs", "html", "css",
        "tailwind", "redux", "svelte", "jquery", "webpack", "sass",
    ],
    "Backend": [
        "spring boot|springboot", "spring framework", "hibernate", "jpa", "node.js|nodejs", "express",
        "django", "flask", "fastapi", "laravel", "ruby on rails|rails", "asp.net|.net|dotnet",
        "graphql", "rest api|restful|rest apis", "microservices", "grpc",
    ],
    "Mobile": ["android", "ios", "flutter", "react native", "swiftui", "xamarin"],
    "Data & AI": [
        "machine learning|ml", "deep learning", "nlp|natural language processing", "computer vision",
        "pytorch", "tensorflow", "scikit-learn|sklearn", "pandas", "numpy", "spark|apache spark|pyspark",
        "hadoop", "airflow", "dbt", "etl", "data modeling", "data warehousing", "power bi|powerbi",
        "tableau", "looker", "excel|microsoft excel", "statistics", "a/b testing", "llm|large language models",
        "generative ai|genai", "langchain", "rag|retrieval augmented generation", "data analysis",
        "data visualization",
    ],
    "Databases": [
        "postgresql|postgres", "mysql", "mongodb", "redis", "elasticsearch", "oracle", "sql server|mssql",
        "dynamodb", "cassandra", "snowflake", "bigquery", "redshift", "sqlite", "neo4j",
    ],
    "Cloud & DevOps": [
        "aws|amazon web services", "azure", "gcp|google cloud", "docker", "kubernetes|k8s", "terraform",
        "ansible", "jenkins", "ci/cd|cicd", "github actions", "gitlab", "linux", "prometheus",
        "grafana", "helm", "nginx", "serverless",
    ],
    "Messaging": ["kafka", "rabbitmq", "sqs", "pubsub|pub/sub"],
    "Testing/QA": [
        "junit", "mockito", "testng", "selenium", "cypress", "playwright", "jest", "pytest",
        "postman", "unit testing", "test automation", "tdd",
    ],
    "Security": [
        "oauth|oauth2", "jwt", "owasp", "penetration testing|pentest", "siem", "iam", "soc 2|soc2",
        "cissp", "cybersecurity",
    ],
    "Design": [
        "figma", "sketch", "adobe xd", "photoshop", "illustrator", "ux research", "ui design",
        "ux design", "prototyping", "wireframing", "design systems",
    ],
    "Product & Delivery": [
        "jira", "agile", "scrum", "kanban", "product roadmap|roadmapping", "stakeholder management",
        "okr|okrs", "confluence", "project management", "pmp", "product management",
    ],
    "Marketing": [
        "seo", "sem", "google analytics", "google ads", "meta ads|facebook ads", "content marketing",
        "email marketing", "hubspot", "copywriting", "social media marketing", "crm", "growth marketing",
    ],
    "Sales & Support": [
        "salesforce", "lead generation", "b2b", "saas", "account management", "cold calling",
        "negotiation", "customer success", "zendesk",
    ],
    "Finance": [
        "financial modeling", "gaap", "ifrs", "quickbooks", "sap", "accounts payable",
        "accounts receivable", "budgeting", "forecasting", "auditing", "cpa", "cfa", "tally",
    ],
    "HR": ["recruiting|talent acquisition", "payroll", "hris", "workday", "onboarding"],
    "Operations": ["supply chain", "logistics", "six sigma", "lean", "erp", "procurement"],
}

ALIAS_TO_CANON: dict = {}
CANON_CATEGORY: dict = {}
for _cat, _entries in SKILLS.items():
    for _entry in _entries:
        _canon, *_aliases = _entry.split("|")
        CANON_CATEGORY[_canon] = _cat
        for _a in (_canon, *_aliases):
            ALIAS_TO_CANON[_a.lower()] = _canon

# A skill must not be glued to letters/digits/+/# ("java" must not match "javascript", "c" not "c++").
BOUND_L = r"(?<![A-Za-z0-9+#])"
BOUND_R = r"(?![A-Za-z0-9+#])"


def any_term_regex(terms: Iterable[str]) -> re.Pattern:
    alts = sorted({re.escape(t.lower()) for t in terms if t}, key=len, reverse=True)
    return re.compile(BOUND_L + "(?:" + "|".join(alts) + ")" + BOUND_R if alts else r"(?!x)x")


@lru_cache(maxsize=4096)
def term_regex(term: str) -> re.Pattern:
    return re.compile(BOUND_L + re.escape(term.lower()) + BOUND_R)


_COMBINED = re.compile(BOUND_L + "(" + "|".join(
    re.escape(a) for a in sorted(ALIAS_TO_CANON, key=len, reverse=True)) + ")" + BOUND_R)


def extract_skills(text_lower: str) -> Set[str]:
    """Canonical skills mentioned in already-lowercased text (one regex pass)."""
    return {ALIAS_TO_CANON[m] for m in _COMBINED.findall(text_lower)}


def count_skills(text_lower: str) -> Counter:
    """Like extract_skills, but with mention counts (used to rank resume skills)."""
    return Counter(ALIAS_TO_CANON[m] for m in _COMBINED.findall(text_lower))


def normalize_skill(skill: str) -> str:
    s = skill.strip().lower()
    return ALIAS_TO_CANON.get(s, s)


def is_known_skill(canon: str) -> bool:
    return canon in CANON_CATEGORY


def search_skills(query: str, limit: int = 20) -> List[dict]:
    """Autocomplete for the frontend's 'your skills' picker."""
    q = query.strip().lower()
    out = []
    for alias, canon in ALIAS_TO_CANON.items():
        if q in alias:
            out.append({"skill": canon, "category": CANON_CATEGORY[canon]})
    seen, uniq = set(), []
    for item in out:
        if item["skill"] not in seen:
            seen.add(item["skill"])
            uniq.append(item)
    return uniq[:limit]