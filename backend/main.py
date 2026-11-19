"""Job Scraper SaaS API.  Run:  uvicorn main:app --host 0.0.0.0 --port 8000"""
import hashlib
import logging
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Literal, Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import config as C
import engine
import exporter
import resume
from schemas import ScrapeRequest
from skills import SKILLS, search_skills

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")
os.makedirs(C.OUTPUT_DIR, exist_ok=True)

# In-memory store. For multiple workers/instances move JOBS to Redis/Postgres and files to S3.
JOBS: dict = {}
LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=C.MAX_CONCURRENT_JOBS)   # extra jobs wait in "queued"

app = FastAPI(title="Job Scraper API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=C.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


# ---------------- auth (optional) ----------------
def current_owner(x_api_key: Optional[str] = Header(None)) -> str:
    """If API_KEYS is set, a valid X-API-Key is required. Jobs are only visible to their creator."""
    if not C.API_KEYS:
        return "anonymous"
    if not x_api_key or not any(secrets.compare_digest(x_api_key, k) for k in C.API_KEYS):
        raise HTTPException(401, "Missing or invalid X-API-Key.")
    return hashlib.sha256(x_api_key.encode()).hexdigest()[:16]


def get_job(job_id: str, owner: str) -> dict:
    with LOCK:
        job = JOBS.get(job_id)
    if not job or job["owner"] != owner:
        raise HTTPException(404, "Job not found.")
    return job


def update(job_id: str, **fields):
    with LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(fields)


# ---------------- models ----------------
class ScrapeResponse(BaseModel):
    job_id: str
    tasks_planned: int
    warnings: List[str] = []


class StatusResponse(BaseModel):
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    progress: float = 0.0
    tasks_done: int = 0
    tasks_total: int = 0
    total_jobs: Optional[int] = None
    message: Optional[str] = None
    warnings: List[str] = []
    funnel: List[dict] = []
    downloads: Optional[dict] = None


# ---------------- worker ----------------
def run_job(job_id: str, req: ScrapeRequest):
    with LOCK:
        job = JOBS.get(job_id)
        if not job or job["cancel"].is_set():
            if job:
                job["status"] = "cancelled"
            return
        job["status"] = "running"
    cancel = job["cancel"]

    def on_progress(done, total, warning):
        with LOCK:
            j = JOBS.get(job_id)
            if j:
                j["tasks_done"], j["tasks_total"] = done, total
                if warning:
                    j["warnings"].append(warning)

    try:
        result = engine.run(req, on_progress, cancel)
        out = result.df
        funnel = [{"stage": s, "jobs": n} for s, n in result.funnel]
        base = {"funnel": funnel}
        with LOCK:
            JOBS[job_id]["warnings"] = JOBS[job_id]["warnings"] + result.warnings
            warnings = list(JOBS[job_id]["warnings"])
        if out.empty:
            update(job_id, status="done", total_jobs=0, out=out, **base,
                   message="Jobs were found but your filters removed all of them. See 'funnel' to "
                           "see which filter was too strict.")
            return
        path = os.path.join(C.OUTPUT_DIR, f"jobs_{job_id}.xlsx")
        exporter.write_xlsx(out, result.funnel, warnings, path)
        update(job_id, status="done", total_jobs=len(out), out=out, filepath=path, **base)
    except engine.Cancelled:
        update(job_id, status="cancelled", message="Cancelled by user.")
    except Exception as e:                      # noqa: BLE001
        log.exception("job %s failed", job_id)
        update(job_id, status="failed", message=str(e))


def _cleanup_loop():
    while True:
        time.sleep(300)
        cutoff = time.time() - C.JOB_TTL_SECONDS
        with LOCK:
            stale = [k for k, v in JOBS.items() if v["created"] < cutoff and v["status"] in
                     ("done", "failed", "cancelled")]
            removed = [JOBS.pop(k) for k in stale]
        for j in removed:
            if j.get("filepath") and os.path.exists(j["filepath"]):
                os.remove(j["filepath"])


threading.Thread(target=_cleanup_loop, daemon=True).start()


# ---------------- routes ----------------
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/scrape", response_model=ScrapeResponse)
def start_scrape(req: ScrapeRequest, owner: str = Depends(current_owner)):
    regions, warnings = engine.resolve_regions(req.countries, req.cities)
    tasks, w = engine.plan_tasks(req, regions)
    if not tasks:
        raise HTTPException(400, "None of the selected sites support the selected locations.")
    job_id = secrets.token_urlsafe(9)           # unguessable: the id is also the access handle
    with LOCK:
        JOBS[job_id] = {"owner": owner, "status": "queued", "created": time.time(), "cancel": threading.Event(),
                        "tasks_done": 0, "tasks_total": len(tasks), "warnings": list(warnings + w)}
    EXECUTOR.submit(run_job, job_id, req)
    return ScrapeResponse(job_id=job_id, tasks_planned=len(tasks), warnings=warnings + w)


@app.get("/api/scrape/{job_id}", response_model=StatusResponse)
def status(job_id: str, owner: str = Depends(current_owner)):
    j = get_job(job_id, owner)
    total = j["tasks_total"] or 1
    done = j["status"] == "done"
    return StatusResponse(
        status=j["status"], progress=1.0 if done else round(j["tasks_done"] / total, 3),
        tasks_done=j["tasks_done"], tasks_total=j["tasks_total"], total_jobs=j.get("total_jobs"),
        message=j.get("message"), warnings=j["warnings"][-50:], funnel=j.get("funnel", []),
        downloads=({f: f"/api/download/{job_id}?format={f}" for f in ("xlsx", "csv", "json")}
                   if done and j.get("total_jobs") else None))


@app.get("/api/results/{job_id}")
def results(job_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
            owner: str = Depends(current_owner)):
    j = get_job(job_id, owner)
    if j["status"] != "done":
        raise HTTPException(409, f"Job is {j['status']}.")
    out: pd.DataFrame = j["out"]
    chunk = out.iloc[(page - 1) * page_size: page * page_size]
    items = chunk.astype(object).where(chunk.notna(), None).to_dict("records")
    return {"total": len(out), "page": page, "page_size": page_size, "items": items}


@app.get("/api/download/{job_id}")
def download(job_id: str, format: Literal["xlsx", "csv", "json"] = "xlsx",
             owner: str = Depends(current_owner)):
    j = get_job(job_id, owner)
    if j["status"] != "done" or not j.get("total_jobs"):
        raise HTTPException(409, "No results available for download.")
    name = f"jobs_{job_id}"
    if format == "xlsx":
        return FileResponse(j["filepath"], filename=f"{name}.xlsx",
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    out: pd.DataFrame = j["out"]
    if format == "csv":
        return Response(exporter.to_csv_bytes(out), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return Response(out.to_json(orient="records", force_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}.json"'})


@app.post("/api/scrape/{job_id}/cancel")
def cancel(job_id: str, owner: str = Depends(current_owner)):
    j = get_job(job_id, owner)
    j["cancel"].set()
    return {"cancelling": True}


@app.delete("/api/scrape/{job_id}")
def delete(job_id: str, owner: str = Depends(current_owner)):
    j = get_job(job_id, owner)
    j["cancel"].set()
    with LOCK:
        JOBS.pop(job_id, None)
    if j.get("filepath") and os.path.exists(j["filepath"]):
        os.remove(j["filepath"])
    return {"deleted": True}


@app.get("/api/meta")
def meta():
    """Everything a frontend needs to render the search form."""
    return {
        "sites": [{"id": s, "label": C.SITE_LABELS[s], "scope": r["scope"],
                   "countries": sorted(r["countries"]) if r["countries"] else "all"}
                  for s, r in C.SITE_RULES.items()],
        "countries": [C.WORLDWIDE_KEY, "remote"] + sorted(k for k in C.COUNTRY_MAP
                                                          if k not in ("remote", "us", "usa", "uk", "uae", "czechia", "korea")),
        "job_types": ["fulltime", "parttime", "internship", "contract"],
        "experience_levels": list(C.LEVEL_TERMS) + ["any"],
        "work_modes": ["any", "remote", "onsite"],
        "title_match": ["off", "any", "all"],
        "skill_categories": {k: [e.split("|")[0] for e in v] for k, v in SKILLS.items()},
        "limits": {"max_results_per_site": C.MAX_RESULTS_PER_SITE, "max_tasks_per_job": C.MAX_TASKS_PER_JOB,
                   "max_top_n": 1000},
    }


@app.get("/api/countries")
def countries():
    return [C.WORLDWIDE_KEY] + sorted(C.COUNTRY_MAP)


@app.get("/api/skills")
def skills(q: str = Query("", max_length=40), limit: int = Query(20, ge=1, le=50)):
    return search_skills(q, limit)


@app.post("/api/resume/analyze")
def analyze_resume_upload(file: UploadFile = File(...), owner: str = Depends(current_owner)):
    """Upload a PDF/DOCX/TXT resume -> profile + `suggested_request` to pre-fill the search form.
    The file is parsed in memory and discarded; nothing is stored or logged."""
    data = file.file.read(resume.MAX_BYTES + 1)
    try:
        text = resume.extract_text(file.filename or "", file.content_type or "", data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return resume.analyze_resume(text)