"""Scrape -> dedupe -> filter -> rank. Framework-agnostic (no FastAPI imports)."""
import logging
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

import pandas as pd
from jobspy import scrape_jobs

import config as C
from schemas import ScrapeRequest
from skills import (any_term_regex, extract_skills, is_known_skill, normalize_skill, term_regex)

log = logging.getLogger("scraper")

# Shared across ALL running jobs, so many users at once can't hammer one site.
SITE_SEMAPHORES = {s: threading.BoundedSemaphore(r["max_parallel"]) for s, r in C.SITE_RULES.items()}
LEVEL_RX = {lvl: any_term_regex(terms) for lvl, terms in C.LEVEL_TERMS.items()}
YEARS_RX = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:to|-|\u2013)\s*\d{1,2}\s*)?(?:years?|yrs?)"
    r"(?:\s+of)?(?:\s+(?:relevant|professional|work|hands-on|industry|related|proven|total))*\s+experience",
    re.I)


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Region:
    label: str            # location string sent to the job site
    country: str          # key for Indeed's country domain
    remote: bool = False


@dataclass(frozen=True)
class Task:
    site: str
    term: str
    region: Region


@dataclass
class RunResult:
    df: pd.DataFrame
    funnel: List[Tuple[str, int]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ======================= planning =======================
def resolve_regions(countries: List[str], cities: List[str]) -> Tuple[List[Region], List[str]]:
    regions, warnings, seen = [], [], set()

    def add(r: Region):
        k = (r.label.lower(), r.remote)
        if k not in seen:
            seen.add(k)
            regions.append(r)

    keys = list(countries)
    had_remote = "remote" in keys
    if C.WORLDWIDE_KEY in keys:
        keys = [k for k in C.COUNTRY_MAP if k not in ("remote", "usa", "us", "uk", "uae", "czechia", "korea")]
        keys.sort(key=lambda k: (C.PRIORITY.index(k) if k in C.PRIORITY else 999, k))
        if had_remote:
            keys.append("remote")
    for k in keys:
        if k == "remote":
            add(Region("Remote", C.DEFAULT_COUNTRY, True))
        elif k in C.COUNTRY_MAP:
            label = {"usa": "United States", "us": "United States", "uk": "United Kingdom",
                     "uae": "United Arab Emirates", "korea": "South Korea"}.get(k, k.title())
            add(Region(label, C.COUNTRY_MAP[k]))
        else:
            warnings.append(f"Unknown country '{k}' was skipped.")

    for city in cities:
        last = city.split(",")[-1].strip().lower()
        country = C.COUNTRY_MAP.get(last) if last != "remote" else None
        if country is None:
            country = C.DEFAULT_COUNTRY
            warnings.append(f"No country recognised in '{city}' (use 'City, Country'); assuming {C.DEFAULT_COUNTRY}.")
        add(Region(city, country))
    return regions, warnings


def plan_tasks(req: ScrapeRequest, regions: List[Region]) -> Tuple[List[Task], List[str]]:
    terms = [req.search_term, *req.extra_search_terms]
    tasks, warnings, global_done = [], [], set()
    for region in regions:                       # region-major: a cap trims low-priority regions only
        for site in req.sites:
            rule = C.SITE_RULES[site]
            if rule["scope"] == "global":
                for t in terms:
                    if (site, t) not in global_done:
                        global_done.add((site, t))
                        tasks.append(Task(site, t, Region("", C.DEFAULT_COUNTRY)))
                continue
            allowed = rule["countries"]
            if allowed is not None and region.country not in allowed:
                continue
            tasks.extend(Task(site, t, region) for t in terms)
    if len(tasks) > C.MAX_TASKS_PER_JOB:
        warnings.append(f"Search needs {len(tasks)} requests; limited to {C.MAX_TASKS_PER_JOB}. "
                        "Pick fewer countries/sites for full coverage.")
        tasks = tasks[:C.MAX_TASKS_PER_JOB]
    if req.easy_apply and any(s not in ("linkedin", "indeed") for s in req.sites):
        warnings.append("'Easy apply' can only be enforced on LinkedIn and Indeed; other sites are unfiltered.")
    return tasks, warnings


# ======================= scraping =======================
def _google_query(task: Task, hours: Optional[int]) -> str:
    where = "remote" if task.region.remote else f"near {task.region.label}"
    when = ""
    if hours:
        when = (" since yesterday" if hours <= 24 else " in the last 3 days" if hours <= 72
                else " in the last week" if hours <= 168 else " in the last month")
    return f"{task.term} jobs {where}{when}".replace("jobs remote", "remote jobs")


def build_kwargs(task: Task, req: ScrapeRequest, results_wanted: int) -> dict:
    """Translate one request into the arguments a given site actually supports.

    jobspy documents that Indeed accepts only ONE of (hours_old | job_type+is_remote | easy_apply) and
    LinkedIn only ONE of (hours_old | easy_apply). We send the most selective one natively and
    enforce the rest in post-processing, so no filter is silently lost.
    """
    r, site, hours = task.region, task.site, req.hours_old
    kw = dict(site_name=[site], search_term=task.term, results_wanted=results_wanted,
              country_indeed=r.country, verbose=0)
    if r.label:
        kw["location"] = r.label
    if C.PROXIES:
        kw["proxies"] = C.PROXIES
    is_remote = r.remote or req.work_mode == "remote"
    job_type = req.job_types[0] if len(req.job_types) == 1 else None

    if site == "google":
        kw["google_search_term"] = _google_query(task, hours)
    elif site == "linkedin":
        kw["linkedin_fetch_description"] = req.fetch_full_description
        if is_remote:
            kw["is_remote"] = True
        if job_type:
            kw["job_type"] = job_type
        if req.easy_apply:
            kw["easy_apply"] = True
        elif hours:
            kw["hours_old"] = hours
    elif site == "indeed":
        if req.easy_apply:
            kw["easy_apply"] = True
        elif hours:
            kw["hours_old"] = hours
        else:
            if is_remote:
                kw["is_remote"] = True
            if job_type:
                kw["job_type"] = job_type
    else:
        if is_remote:
            kw["is_remote"] = True
        if job_type:
            kw["job_type"] = job_type
        if hours:
            kw["hours_old"] = hours
    return kw


def scrape_one(task: Task, req: ScrapeRequest, results_wanted: int,
               cancel: threading.Event) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    kw = build_kwargs(task, req, results_wanted)
    err = "unknown error"
    for attempt in range(C.SCRAPE_RETRIES + 1):
        if cancel.is_set():
            return None, "cancelled"
        try:
            with SITE_SEMAPHORES[task.site]:          # only the network call holds the slot
                df = scrape_jobs(**kw)
            return df, None
        except Exception as e:                        # noqa: BLE001 - any site failure is non-fatal
            err = str(e)[:200] or e.__class__.__name__
            if attempt < C.SCRAPE_RETRIES:
                time.sleep(2 ** attempt + random.random())
    return None, err


# ======================= filtering =======================
def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(_dl=df["description"].fillna("").astype(str).str.len())
    df = df.sort_values("_dl", ascending=False)       # keep the richest copy of a duplicate
    df = df.drop_duplicates(subset="job_url")
    city = df["location"].fillna("").astype(str).str.split(",").str[0].str.strip().str.lower()
    key = (df["title"].astype(str).str.lower().str.strip() + "|"
           + df["company"].fillna("").astype(str).str.lower().str.strip() + "|" + city)
    return df.assign(_key=key).drop_duplicates("_key").drop(columns=["_dl", "_key"])


def _stage_date(df, req):
    if not req.hours_old:
        return None
    cutoff = pd.Timestamp(datetime.now() - timedelta(hours=req.hours_old)).normalize()
    dp = pd.to_datetime(df["date_posted"], errors="coerce")
    return df[dp.isna() | (dp >= cutoff)]             # unknown dates are kept, not punished


def _stage_work_mode(df, req):
    if req.work_mode == "any":
        return None
    flag = df["is_remote"].fillna(False).astype(bool)
    hint = (df["_title"] + " " + df["location"].fillna("").astype(str).str.lower()).str.contains(r"\bremote\b")
    remote = flag | hint
    return df[remote] if req.work_mode == "remote" else df[~remote]


def _stage_job_type(df, req):
    if not req.job_types:
        return None
    jt = (df["job_type"].fillna("").astype(str).str.lower()
          .str.replace(r"[-_ ]", "", regex=True))
    keep = (jt == "") | jt.map(lambda s: any(t in s for t in req.job_types))
    return df[keep]


def _stage_salary(df, req):
    if req.min_salary_annual is None and not req.require_salary:
        return None
    mult = df["interval"].fillna("yearly").astype(str).str.lower().map(C.INTERVAL_MULT).fillna(1)
    top = df["max_amount"].fillna(df["min_amount"]) * mult
    known = top.notna()
    if req.salary_currency:
        known &= df["currency"].fillna("").astype(str).str.upper() == req.salary_currency.upper()
    thr = req.min_salary_annual or 0
    keep = (known & (top >= thr)) if req.require_salary else (~known | (top >= thr))
    return df[keep]


def _stage_experience(df, req):
    levels = set(req.experience_levels) - {"any"}
    max_years = req.max_experience_years
    if max_years is None and levels and levels <= {"intern", "entry"}:
        max_years = 3                                  # sensible default for fresher/entry searches
    if not levels and max_years is None:
        return None
    keep = pd.Series(True, index=df.index)
    if levels:
        def level_ok(title):
            found = {lvl for lvl, rx in LEVEL_RX.items() if rx.search(title)}
            return (not found) or bool(found & levels)  # untagged titles are never dropped
        keep &= df["_title"].map(level_ok)
    if max_years is not None:
        def years_ok(text):
            nums = [int(m) for m in YEARS_RX.findall(text)]
            return not nums or max(nums) <= max_years
        keep &= df["_text"].map(years_ok)
    return df[keep]


def _stage_keywords(df, req):
    if not (req.must_include_any or req.must_include_all or req.exclude_keywords):
        return None
    keep = pd.Series(True, index=df.index)
    if req.must_include_any:
        rx = any_term_regex(req.must_include_any)
        keep &= df["_text"].map(lambda t: bool(rx.search(t)))
    for k in req.must_include_all:
        rx = term_regex(k)
        keep &= df["_text"].map(lambda t, rx=rx: bool(rx.search(t)))
    if req.exclude_keywords:
        rx = any_term_regex(req.exclude_keywords)
        keep &= ~df["_text"].map(lambda t: bool(rx.search(t)))
    return df[keep]


def _tokens(term: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9+#.]+", term.lower()) if t not in C.STOPWORDS and len(t) > 1]


def _stage_title(df, req):
    if req.title_match == "off":
        return None
    toks = sorted({t for term in [req.search_term, *req.extra_search_terms] for t in _tokens(term)})
    if not toks:
        return None
    if req.title_match == "any":
        rx = any_term_regex(toks)
        return df[df["_title"].map(lambda t: bool(rx.search(t)))]
    # "all": every token of at least one query must appear in the title
    per_term = [_tokens(t) for t in [req.search_term, *req.extra_search_terms]]
    rxs = [[term_regex(t) for t in toks_] for toks_ in per_term if toks_]
    keep = df["_title"].map(lambda title: any(all(rx.search(title) for rx in group) for group in rxs))
    return df[keep]


def _stage_company(df, req):
    if not (req.company_include or req.company_exclude):
        return None
    comp = df["company"].fillna("").astype(str).str.lower()
    keep = pd.Series(True, index=df.index)
    if req.company_include:
        keep &= comp.map(lambda c: any(k in c for k in req.company_include))
    if req.company_exclude:
        keep &= ~comp.map(lambda c: any(k in c for k in req.company_exclude))
    return df[keep]


STAGES = [("Posted within window", _stage_date), ("Work mode", _stage_work_mode),
          ("Job type", _stage_job_type), ("Salary", _stage_salary),
          ("Experience level", _stage_experience), ("Keywords", _stage_keywords),
          ("Title match", _stage_title), ("Company", _stage_company)]


# ======================= ranking + skills =======================
def _rank(df: pd.DataFrame, req: ScrapeRequest) -> pd.DataFrame:
    toks = sorted({t for term in [req.search_term, *req.extra_search_terms] for t in _tokens(term)})
    phrases = [t.lower() for t in [req.search_term, *req.extra_search_terms]]
    mine = {normalize_skill(s) for s in req.my_skills}
    custom = [(s, term_regex(s)) for s in mine if not is_known_skill(s)]
    dp = pd.to_datetime(df["date_posted"], errors="coerce")
    today = pd.Timestamp.now().normalize()
    has_salary = (df["min_amount"].notna() | df["max_amount"].notna()).tolist()

    scores, mentioned, matched_l, gaps_l, pct_l = [], [], [], [], []
    for title, text, posted, sal in zip(df["_title"], df["_text"], dp, has_salary):
        skills = extract_skills(text) | {c for c, rx in custom if rx.search(text)}
        matched, gaps = skills & mine, skills - mine
        s = sum(10 for p in phrases if p in title)
        s += 5 * sum(1 for t in toks if term_regex(t).search(title))
        s += 0.5 * min(8, sum(1 for t in toks if term_regex(t).search(text)))
        for kw in req.boost_keywords:
            rx = term_regex(kw)
            s += 3 if rx.search(title) else 1.5 if rx.search(text) else 0
        s += 2 * len(matched)
        if pd.notna(posted):
            age = (today - posted).days
            s += 3 if age <= 1 else 2 if age <= 3 else 1 if age <= 7 else 0
        s += 0.5 if sal else 0
        scores.append(round(s, 1))
        mentioned.append(", ".join(sorted(skills)))
        matched_l.append(", ".join(sorted(matched)) if mine else "")
        gaps_l.append(", ".join(sorted(gaps)) if mine else "")
        pct_l.append(round(100 * len(matched) / len(skills)) if mine and skills else None)

    df = df.assign(_score=scores, _dp=dp, _mentioned=mentioned, _matched=matched_l,
                   _gaps=gaps_l, _pct=pct_l)
    return df.sort_values(["_score", "_dp"], ascending=[False, False], na_position="last")


def _salary_str(row) -> str:
    lo, hi = row["min_amount"], row["max_amount"]
    if pd.isna(lo) and pd.isna(hi):
        return ""
    cur = row["currency"] if pd.notna(row["currency"]) else ""
    iv = f" / {row['interval']}" if pd.notna(row["interval"]) else ""
    rng = f"{lo:,.0f}-{hi:,.0f}" if pd.notna(lo) and pd.notna(hi) else f"{(lo if pd.notna(lo) else hi):,.0f}"
    return f"{cur} {rng}{iv}".strip()


def to_output_frame(df: pd.DataFrame) -> pd.DataFrame:
    remote = df["is_remote"].map(lambda v: "" if pd.isna(v) else "Yes" if bool(v) else "No")
    return pd.DataFrame({
        "Platform": df["site"].map(lambda s: C.SITE_LABELS.get(s, s)),
        "Job Title": df["title"],
        "Company": df["company"],
        "Location": df["location"],
        "Remote": remote,
        "Job Type": df["job_type"],
        "Salary": df.apply(_salary_str, axis=1),
        "Date Posted": df["_dp"].dt.strftime("%Y-%m-%d").fillna(""),
        "Relevance": df["_score"],
        "Skill Match %": df["_pct"],
        "Matched Skills": df["_matched"],
        "Skill Gaps": df["_gaps"],
        "Skills Mentioned": df["_mentioned"],
        "Job URL Link": df["job_url"],
        "Search Term": df["search_term"],
        "Application Status": "Not Applied",
        "Date Applied": "",
        "Follow-up Notes": "",
    }).reset_index(drop=True)


def process(frames: List[pd.DataFrame], req: ScrapeRequest) -> Tuple[pd.DataFrame, List[Tuple[str, int]]]:
    funnel = []
    df = pd.concat(frames, ignore_index=True)
    for col in C.EXPECTED_COLUMNS:
        if col not in df.columns:
            df[col] = None
    for col in ("min_amount", "max_amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    funnel.append(("Scraped", len(df)))

    df = df[df["title"].notna() & df["job_url"].notna()]
    df = _dedupe(df).reset_index(drop=True)
    funnel.append(("After de-duplication", len(df)))

    df["_title"] = df["title"].fillna("").astype(str).str.lower()
    df["_text"] = df["_title"] + " " + df["description"].fillna("").astype(str).str.lower()
    for name, fn in STAGES:
        if df.empty:
            break
        out = fn(df, req)
        if out is not None:
            df = out
            funnel.append((name, len(df)))
    if df.empty:
        return pd.DataFrame(), funnel
    df = _rank(df, req).head(req.top_n)
    funnel.append(("Final (top N)", len(df)))
    return to_output_frame(df), funnel


# ======================= orchestration =======================
def run(req: ScrapeRequest,
        on_progress: Callable[[int, int, Optional[str]], None],
        cancel: threading.Event) -> RunResult:
    regions, warnings = resolve_regions(req.countries, req.cities)
    if not regions and not any(C.SITE_RULES[s]["scope"] == "global" for s in req.sites):
        raise ValueError("No valid locations. Use country names, 'remote', 'worldwide' or 'City, Country'.")
    tasks, w = plan_tasks(req, regions)
    warnings += w
    if not tasks:
        raise ValueError("None of the selected sites support the selected locations "
                         "(e.g. ZipRecruiter is US/Canada only, Naukri is India only).")

    results_wanted = min(req.results_per_site, C.MAX_RESULTS_PER_SITE)
    frames, done = [], 0
    on_progress(0, len(tasks), None)
    with ThreadPoolExecutor(max_workers=C.MAX_PARALLEL_TASKS) as pool:
        futures = {pool.submit(scrape_one, t, req, results_wanted, cancel): t for t in tasks}
        for fut in as_completed(futures):
            t = futures[fut]
            df, err = fut.result()
            done += 1
            msg = None
            if err and err != "cancelled":
                msg = f"{C.SITE_LABELS[t.site]} | {t.region.label or 'global'} | {t.term}: {err}"
            elif df is not None and len(df):
                df = df.copy()
                df["search_term"] = t.term
                frames.append(df)
            on_progress(done, len(tasks), msg)
    if cancel.is_set():
        raise Cancelled()
    if not frames:
        raise ValueError("No jobs came back from any site. Check the warnings; sites may be rate-limiting "
                         "(add proxies via SCRAPER_PROXIES).")
    out, funnel = process(frames, req)
    return RunResult(out, funnel, warnings)
