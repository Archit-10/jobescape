"""Static configuration + environment-driven settings."""
import os


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# ---------------- runtime settings (override via env vars) ----------------
MAX_RESULTS_PER_SITE = _int("MAX_RESULTS_PER_SITE", 100)   # hard cap per site/location/term
MAX_PARALLEL_TASKS = _int("MAX_PARALLEL_TASKS", 12)        # threads per job
MAX_TASKS_PER_JOB = _int("MAX_TASKS_PER_JOB", 150)         # site x location x term cap (protects your IPs)
MAX_CONCURRENT_JOBS = _int("MAX_CONCURRENT_JOBS", 2)       # jobs running at once; the rest queue
SCRAPE_RETRIES = _int("SCRAPE_RETRIES", 2)
JOB_TTL_SECONDS = _int("JOB_TTL_SECONDS", 3600)            # results are deleted after this
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "scraped")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
API_KEYS = {k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()}  # empty = auth off
# Rotating proxies, e.g. SCRAPER_PROXIES="user:pass@host:port,user:pass@host2:port"
PROXIES = [p.strip() for p in os.getenv("SCRAPER_PROXIES", "").split(",") if p.strip()] or None

# ---------------- countries ----------------
COUNTRY_MAP = {
    "argentina": "argentina", "australia": "australia", "austria": "austria",
    "bahrain": "bahrain", "bangladesh": "bangladesh", "belgium": "belgium",
    "bulgaria": "bulgaria", "brazil": "brazil", "canada": "canada",
    "chile": "chile", "china": "china", "colombia": "colombia",
    "costa rica": "costa rica", "croatia": "croatia", "cyprus": "cyprus",
    "czech republic": "czechia", "denmark": "denmark", "ecuador": "ecuador",
    "egypt": "egypt", "estonia": "estonia", "finland": "finland",
    "france": "france", "germany": "germany", "greece": "greece",
    "hong kong": "hong kong", "hungary": "hungary", "india": "india",
    "indonesia": "indonesia", "ireland": "ireland", "israel": "israel",
    "italy": "italy", "japan": "japan", "kuwait": "kuwait",
    "latvia": "latvia", "lithuania": "lithuania", "luxembourg": "luxembourg",
    "malaysia": "malaysia", "malta": "malta", "mexico": "mexico",
    "morocco": "morocco", "netherlands": "netherlands", "new zealand": "new zealand",
    "nigeria": "nigeria", "norway": "norway", "oman": "oman",
    "pakistan": "pakistan", "panama": "panama", "peru": "peru",
    "philippines": "philippines", "poland": "poland", "portugal": "portugal",
    "qatar": "qatar", "romania": "romania", "saudi arabia": "saudi arabia",
    "singapore": "singapore", "slovakia": "slovakia", "slovenia": "slovenia",
    "south africa": "south africa", "south korea": "south korea", "spain": "spain",
    "sweden": "sweden", "switzerland": "switzerland", "taiwan": "taiwan",
    "thailand": "thailand", "turkey": "turkey", "ukraine": "ukraine",
    "united arab emirates": "united arab emirates", "united kingdom": "uk",
    "united states": "usa", "uruguay": "uruguay", "venezuela": "venezuela",
    "vietnam": "vietnam",
    "remote": "usa",
}
# Aliases people actually type
COUNTRY_MAP.update({"usa": "usa", "us": "usa", "uk": "uk", "uae": "united arab emirates",
                    "czechia": "czechia", "korea": "south korea"})

WORLDWIDE_KEY = "worldwide"
DEFAULT_COUNTRY = "usa"

# Big markets first, so if MAX_TASKS_PER_JOB trims a worldwide search, the best regions survive.
PRIORITY = ["united states", "india", "united kingdom", "canada", "germany", "australia",
            "singapore", "united arab emirates", "netherlands", "france", "ireland", "spain",
            "poland", "brazil", "mexico", "japan", "sweden", "switzerland", "italy"]

# ---------------- platforms ----------------
ALL_SITES = ["linkedin", "indeed", "glassdoor", "zip_recruiter", "google", "bayt", "naukri", "bdjobs"]

# Glassdoor / ZipRecruiter only work in some countries (per jobspy docs; verify against your installed version).
GLASSDOOR_COUNTRIES = {"australia", "austria", "belgium", "brazil", "canada", "france", "germany",
                       "hong kong", "india", "ireland", "italy", "mexico", "netherlands",
                       "new zealand", "singapore", "spain", "switzerland", "uk", "usa", "vietnam"}

# scope "region": one request per location.  scope "global": one request per search term.
# max_parallel: simultaneous requests per site across ALL jobs (rate-limit protection).
SITE_RULES = {
    "linkedin":      {"countries": None,                    "scope": "region", "max_parallel": 2},
    "indeed":        {"countries": None,                    "scope": "region", "max_parallel": 4},
    "glassdoor":     {"countries": GLASSDOOR_COUNTRIES,     "scope": "region", "max_parallel": 3},
    "zip_recruiter": {"countries": {"usa", "canada"},       "scope": "region", "max_parallel": 3},
    "google":        {"countries": None,                    "scope": "region", "max_parallel": 2},
    "bayt":          {"countries": None,                    "scope": "global", "max_parallel": 2},
    "naukri":        {"countries": {"india"},               "scope": "region", "max_parallel": 2},
    "bdjobs":        {"countries": {"bangladesh"},          "scope": "region", "max_parallel": 2},
}

SITE_LABELS = {"linkedin": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor",
               "zip_recruiter": "ZipRecruiter", "google": "Google Jobs", "bayt": "Bayt",
               "naukri": "Naukri", "bdjobs": "BDJobs"}

# ---------------- filters ----------------
# Seniority is matched against the JOB TITLE only (so "reports to the senior manager" in a
# description can't wrongly remove a junior role). "manager" is deliberately absent: Product/Project
# Manager is a role, not a seniority level.
LEVEL_TERMS = {
    "intern":    ["intern", "internship", "trainee", "apprentice", "working student", "co-op"],
    "entry":     ["junior", "jr", "entry level", "entry-level", "fresher", "graduate", "new grad",
                  "associate", "early career"],
    "mid":       ["mid-level", "mid level", "intermediate"],
    "senior":    ["senior", "sr"],
    "lead":      ["lead", "staff", "principal", "architect"],
    "executive": ["director", "vp", "vice president", "chief", "head of", "president"],
}

INTERVAL_MULT = {"yearly": 1, "monthly": 12, "weekly": 52, "daily": 260, "hourly": 2080}

STOPWORDS = {"and", "or", "the", "of", "a", "an", "in", "for", "to", "at", "with", "job", "jobs",
             "remote", "hiring", "position", "role"}

EXPECTED_COLUMNS = ["site", "title", "company", "job_url", "location", "date_posted", "job_type",
                    "is_remote", "min_amount", "max_amount", "interval", "currency", "description"]
