"""Resume -> job-search profile. Offline and rule-based: nothing is stored, logged or sent anywhere.

analyze_resume(text) keeps the original keys (suggested_search, skills, years_experience, summary) and
adds structured data plus `suggested_request`, a dict you can merge straight into a ScrapeRequest.
"""
import io
import math
import re
from collections import Counter
from datetime import date
from typing import Dict, List, Optional, Tuple

from config import COUNTRY_MAP
from skills import ALIAS_TO_CANON, CANON_CATEGORY, count_skills

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
MAX_CHARS = 60_000
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ======================= text extraction =======================
def extract_text(filename: str, content_type: str, data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError("Resume is too large (max 5 MB).")
    name, ctype = (filename or "").lower(), (content_type or "").lower()
    try:
        if name.endswith(".pdf") or ctype == "application/pdf":
            text = _pdf_text(data)
        elif name.endswith(".docx") or ctype == DOCX_MIME:
            text = _docx_text(data)
        elif name.endswith(".doc"):
            raise ValueError("Old .doc files aren't supported. Save the resume as DOCX or PDF.")
        elif name.endswith(".txt") or ctype.startswith("text/"):
            text = data.decode("utf-8", errors="replace")
        else:
            raise ValueError("Unsupported resume format. Upload PDF, DOCX, or TXT.")
    except ValueError:
        raise
    except Exception as exc:  # corrupt file, parser crash, ...
        raise ValueError("Couldn't read this file. It may be corrupted or password-protected.") from exc
    text = _normalize(text)
    if len(text) < 50:
        raise ValueError("No readable text found. Scanned/image-only resumes aren't supported yet; "
                         "upload a text-based PDF or a DOCX.")
    return text


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ValueError("This PDF is password-protected.")
    return "\n".join((p.extract_text() or "") for p in reader.pages[:MAX_PAGES])


def _docx_text(data: bytes) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(io.BytesIO(data))
    parts: List[str] = []
    for section in doc.sections:                       # contact details often live in the header
        parts += [p.text for p in section.header.paragraphs]
    for child in doc.element.body.iterchildren():      # body order, so tables stay in place
        if child.tag.endswith("}p"):
            parts.append(Paragraph(child, doc).text)
        elif child.tag.endswith("}tbl"):
            for row in Table(child, doc).rows:
                seen = []
                for cell in row.cells:                 # merged cells repeat their text
                    t = cell.text.strip()
                    if t and t not in seen:
                        seen.append(t)
                parts.extend(seen)
    return "\n".join(parts)


def _normalize(text: str) -> str:
    text = text.replace("\r", "\n").replace("\x0c", "\n").replace("\xa0", " ")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"^[\s\u2022\u25cf\u25aa\u25e6\u25a0\u25a1\u27a2\u27a4\u25b6\u25ba\u00b7*]+", "", line)
        line = re.sub(r"^-\s+", "", line)
        lines.append(re.sub(r"[ \t]+", " ", line).strip())   # keep line breaks: they carry structure
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:MAX_CHARS]


# ======================= sections =======================
_SECTION_NAMES = {
    "summary": ["summary", "professional summary", "profile", "objective", "career objective",
                "about me", "about", "career summary"],
    "experience": ["experience", "work experience", "professional experience", "employment",
                   "employment history", "work history", "internships", "internship experience",
                   "relevant experience"],
    "education": ["education", "academic background", "academics", "qualifications",
                  "educational qualifications"],
    "skills": ["skills", "technical skills", "key skills", "core competencies", "skills and tools",
               "tech stack", "technologies", "tools", "programming languages", "technical proficiency"],
    "projects": ["projects", "personal projects", "academic projects", "key projects", "open source"],
    "certifications": ["certifications", "certificates", "licenses", "courses", "licenses and certifications"],
    "other": ["achievements", "awards", "publications", "interests", "hobbies", "references",
              "volunteering", "extracurricular", "activities", "declaration"],
}


def _hn(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s.lower().replace("&", " and "))).strip()


_HEAD_LOOKUP = {_hn(h): sec for sec, heads in _SECTION_NAMES.items() for h in heads}


def split_sections(text: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {"header": []}
    current = "header"
    for line in text.split("\n"):
        if not line:
            continue
        if len(line) <= 45 and _hn(line) in _HEAD_LOOKUP:           # "SKILLS", "Work Experience:"
            current = _HEAD_LOOKUP[_hn(line)]
            sections.setdefault(current, [])
            continue
        head, sep, rest = line.partition(":")
        if sep and rest.strip() and len(head) <= 30 and _hn(head) in _HEAD_LOOKUP:   # "Skills: A, B"
            current = _HEAD_LOOKUP[_hn(head)]
            sections.setdefault(current, []).append(rest.strip())
            continue
        sections.setdefault(current, []).append(line)
    return sections


# ======================= small helpers =======================
def _today() -> date:
    return date.today()


_ACRONYMS = {"ux": "UX", "ui": "UI", "qa": "QA", "hr": "HR", "sde": "SDE", "it": "IT", "ai": "AI",
             "ml": "ML", "sap": "SAP", "seo": "SEO", "devops": "DevOps", "sre": "SRE", "bi": "BI"}


def _title_case(s: str) -> str:
    return " ".join(_ACRONYMS.get(w.lower(), w.capitalize() if w.islower() or w.isupper() else w)
                    for w in s.split())


_TITLE_NOUNS = ["engineer", "developer", "programmer", "analyst", "scientist", "designer", "architect",
                "manager", "consultant", "specialist", "executive", "administrator", "accountant",
                "auditor", "recruiter", "coordinator", "associate", "assistant", "officer", "researcher",
                "strategist", "marketer", "writer", "editor", "technician", "representative", "advisor",
                "planner", "tester", "intern", "trainee", "lead", "director", "producer", "copywriter",
                "teacher", "lecturer"]
_TITLE_RX = re.compile(r"\b((?:[A-Za-z][A-Za-z+#./&-]{0,20}\s+){1,3}(?:"
                       + "|".join(sorted(_TITLE_NOUNS, key=len, reverse=True)) + r"))\b", re.I)
_LEAD_STOP = {"as", "a", "an", "the", "and", "of", "at", "in", "for", "to", "with", "working", "worked",
              "currently", "is", "am", "i", "my", "role", "position", "experienced", "motivated",
              "passionate", "aspiring", "dedicated", "results", "driven", "oriented", "seeking",
              "looking", "become", "being", "been", "was", "were", "highly", "skilled", "talented"}
_LEAD_MODS = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "associate", "head", "chief",
              "entry", "entry-level", "graduate", "fresher", "summer", "trainee", "intern"}
_TRAIL_MODS = {"intern", "trainee", "internship"}


def _title_from_line(line: str) -> Optional[str]:
    for m in _TITLE_RX.finditer(line):
        words = m.group(1).split()
        while words and words[0].lower().strip(".,-") in _LEAD_STOP:
            words.pop(0)
        if len(words) >= 2 and not any(re.search(r"\d", w) for w in words):
            return " ".join(words)
    return None


def _search_term(phrase: str) -> str:
    words = phrase.split()
    while len(words) > 1 and words[0].lower().strip(".,") in _LEAD_MODS:
        words.pop(0)
    while len(words) > 1 and words[-1].lower() in _TRAIL_MODS:
        words.pop()
    return _title_case(" ".join(words))


def _seniority(phrase: str) -> Optional[str]:
    w = {x.lower().strip(".,") for x in phrase.split()}
    if w & {"intern", "internship"}:
        return "intern"
    if w & {"lead", "principal", "staff", "architect", "head", "director"}:
        return "lead"
    if w & {"senior", "sr"}:
        return "senior"
    if w & {"junior", "jr", "associate", "graduate", "trainee", "fresher", "entry"}:
        return "entry"
    return None


# ======================= identity & links =======================
_NOT_NAME = {"resume", "curriculum", "vitae", "cv", "profile", "summary", "objective", "contact", "portfolio"}
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_LINKEDIN = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w%-]+", re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
_URL = re.compile(r"(?:https?://|www\.)[^\s,;|)>\]]+", re.I)
_DOMAIN = re.compile(r"\b[a-z0-9-]+\.(?:dev|io|me|com|net|org|in|co|app|tech)\b(?:/[\w./-]*)?", re.I)


def _name(header: List[str]) -> Optional[str]:
    for line in header[:4]:
        low = line.lower()
        if "@" in line or re.search(r"\d|http|www\.", low) or len(line) > 40:
            continue
        words = [w for w in re.split(r"[\s,]+", line.strip()) if w]
        if not 2 <= len(words) <= 4:
            continue
        if any(w.lower().strip(".") in _NOT_NAME or w.lower() in _TITLE_NOUNS for w in words):
            continue
        if all(re.fullmatch(r"[A-Za-z][A-Za-z.'\u2019-]*", w) for w in words):
            return " ".join(w.capitalize() if w.isupper() else w for w in words)
    return None


def _https(u: str) -> str:
    u = u.rstrip(".,;")
    return u if u.lower().startswith("http") else "https://" + u


def _links(text: str, header: List[str]) -> Tuple[Optional[str], Dict[str, str]]:
    email = _EMAIL.search(text)
    links: Dict[str, str] = {}
    if m := _LINKEDIN.search(text):
        links["linkedin"] = _https(m.group(0))
    if m := _GITHUB.search(text):
        links["github"] = _https(m.group(0))
    for m in _URL.finditer(text):
        if not re.search(r"linkedin\.com|github\.com", m.group(0), re.I):
            links["website"] = _https(m.group(0))
            break
    if "website" not in links:                      # bare domains in the header, e.g. "myname.dev"
        head = _EMAIL.sub(" ", " ".join(header[:8]))
        for m in _DOMAIN.finditer(head):
            if not re.search(r"linkedin|github", m.group(0), re.I):
                links["website"] = _https(m.group(0))
                break
    return (email.group(0) if email else None), links


# ======================= role =======================
def _detect_role(sections: Dict[str, List[str]]) -> Optional[dict]:
    scores: Dict[str, float] = {}
    best: Dict[str, Tuple[float, str, str]] = {}      # key -> (weight, raw phrase, source)

    def add(phrase: str, weight: float, source: str):
        key = _search_term(phrase).lower()
        scores[key] = scores.get(key, 0) + weight
        if key not in best or weight > best[key][0]:
            best[key] = (weight, phrase, source)

    for i, line in enumerate(sections.get("header", [])[:10]):
        for seg in re.split(r"[|\u2022\u00b7]", line):          # "Title | City | email | links"
            if len(seg) <= 60 and "@" not in seg and (p := _title_from_line(seg)):
                add(p, 3.0 - 0.1 * i, "headline")
                break
    first = True
    for line in sections.get("experience", [])[:80]:
        words = line.split()
        if 1 < len(words) <= 12 and line[0].isupper() and not line.endswith(".") and (p := _title_from_line(line)):
            add(p, 2.5 if first else 1.0, "experience")
            first = False
    for line in sections.get("summary", [])[:3]:
        if len(line) <= 200 and (p := _title_from_line(line)):
            add(p, 1.5, "summary")
            break
    if not scores:
        return None
    key = max(scores, key=lambda k: scores[k])
    _, phrase, source = best[key]
    return {"phrase": phrase, "source": source}


# ======================= experience (years from date ranges) =======================
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun",
                                    "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_D = (r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s*(?:'|\u2019)?\d{2,4}"
      r"|\d{1,2}/\d{4}|(?:19|20)\d{2})")
_RANGE_RX = re.compile(rf"({_D})\s*(?:-|\u2013|\u2014|to|until|till)\s*"
                       rf"({_D}|present|current|now|ongoing|date|today)", re.I)
_PRESENT = {"present", "current", "now", "ongoing", "date", "today"}


def _parse_date(tok: str, is_end: bool) -> Optional[Tuple[int, int, bool]]:
    t = tok.lower().strip()
    today = _today()
    if t in _PRESENT:
        return today.year, today.month, True
    if m := re.match(r"(\d{1,2})/(\d{4})$", t):
        return int(m.group(2)), min(max(int(m.group(1)), 1), 12), True
    y = re.search(r"(?:19|20)\d{2}", t) or re.search(r"\d{2}$", t)
    if not y:
        return None
    year = int(y.group(0))
    year += 2000 if year < 100 else 0
    mon = _MON.get(t[:3]) if t[:3] in _MON else None
    if mon:
        return year, mon, True
    if is_end and year == today.year:
        return year, today.month, False
    return year, (6 if is_end else 7), False          # year-only: assume mid-year (unbiased on average)


def _intervals(lines: List[str]) -> List[Tuple[int, int]]:
    today = _today()
    now = today.year * 12 + today.month
    out = []
    for line in lines:
        if len(line) > 200:
            continue
        for m in _RANGE_RX.finditer(line):
            s, e = _parse_date(m.group(1), False), _parse_date(m.group(2), True)
            if not s or not e:
                continue
            a, b = s[0] * 12 + s[1], min(e[0] * 12 + e[1], now)
            if b <= a and not (s[2] is False and e[2] is False and s[0] == e[0]):
                continue
            if b <= a:
                b = a + 6                              # "2022 - 2022": call it half a year
            if a < 1970 * 12 or b - a > 45 * 12:
                continue
            out.append((a, b))
    return out


def _merge_months(iv: List[Tuple[int, int]]) -> int:
    total, cur_s, cur_e = 0, None, None
    for a, b in sorted(iv):
        if cur_e is None or a > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = a, b
        else:
            cur_e = max(cur_e, b)
    return total + (cur_e - cur_s if cur_e is not None else 0)


_STATED_YEARS = [
    re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:[a-z-]+\s+){0,2}experience"),
    re.compile(r"experience\s+(?:of\s+)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)"),
]


def _years(sections: Dict[str, List[str]], lower: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    exp_lines = sections.get("experience") or [
        l for sec, ls in sections.items()
        if sec in ("header", "summary") for l in ls]
    computed = _merge_months(_intervals(exp_lines)) / 12 or None
    head = " ".join(sections.get("header", []) + sections.get("summary", [])).lower()
    stated = None
    for src in (head, lower):
        nums = [int(n) for rx in _STATED_YEARS for n in rx.findall(src) if int(n) <= 40]
        if nums:
            stated = float(max(nums))
            break
    computed = round(computed, 1) if computed else None
    known = [x for x in (stated, computed) if x is not None]
    final = max(known) if known else None             # "6+ years" is a floor; dates may show more
    return final, computed, stated


def _levels(years: Optional[float], seniority: Optional[str], student: bool) -> List[str]:
    if years is None:
        if student:
            return ["intern", "entry"]
        return {"intern": ["intern", "entry"], "entry": ["entry"], "senior": ["senior", "lead"],
                "lead": ["lead", "senior"]}.get(seniority or "", [])
    if years < 1:
        return ["intern", "entry"]
    if years < 3:
        return ["entry", "mid"]
    if years < 6:
        return ["mid", "senior"]
    if years < 10:
        return ["senior", "lead"]
    return ["senior", "lead", "executive"]


# ======================= education =======================
_DEGREES = [
    ("PhD", 4, re.compile(r"\bph\.?\s?d\b|\bdoctorate\b", re.I)),
    ("Master's", 3, re.compile(r"\bm\.?\s?tech\b|\bm\.?\s?sc\b|\bmca\b|\bmba\b|\bmaster'?s?\b|\bm\.?\s?com\b|"
                               r"\bpgdm\b|\bm\.?s\.?\s+in\b|\bm\.?a\.?\s+in\b", re.I)),
    ("Master's", 3, re.compile(r"\bM\.?E\.?(?=[\s,(]|$)")),
    ("Bachelor's", 2, re.compile(r"\bb\.?\s?tech\b|\bb\.?\s?sc\b|\bbca\b|\bbba\b|\bbachelor'?s?\b|\bb\.?\s?com\b|"
                                 r"\bb\.?s\.?\s+in\b|\bb\.?a\.?\s+in\b", re.I)),
    ("Bachelor's", 2, re.compile(r"\bB\.?E\.?(?=[\s,(]|$)")),
    ("Diploma", 1, re.compile(r"\bdiploma\b|\bpolytechnic\b", re.I)),
]
_INSTITUTION = re.compile(r"\b(university|college|institute|school|academy|iit|nit|iiit|polytechnic)\b", re.I)
_STUDENT_WORDS = re.compile(r"pursuing|expected|currently|final year|ongoing|present|till date|in progress", re.I)


def _education(sections: Dict[str, List[str]], all_lines: List[str]):
    lines = sections.get("education") or [l for l in all_lines if _INSTITUTION.search(l)][:6]
    if not lines:
        return None, False
    best = (0, None)
    for line in lines:
        for label, rank, rx in _DEGREES:
            if rx.search(line) and rank > best[0]:
                best = (rank, label)
    institution = None
    for line in lines:
        for seg in re.split(r"\s[|\u2013\u2014-]\s|,|\|", line):
            if _INSTITUTION.search(seg) and 3 < len(seg.strip()) <= 80:
                institution = seg.strip()
                break
        if institution:
            break
    years = [int(y) for l in lines for y in re.findall(r"\b(19[89]\d|20[0-4]\d)\b", l)]
    grad = max(years) if years else None
    text = " ".join(lines)
    signal = bool(_STUDENT_WORDS.search(text)) or bool(grad and grad >= _today().year)
    info = {"degree": best[1], "institution": institution, "graduation_year": grad}
    return (info if any(info.values()) else None), signal


# ======================= skills =======================
_SKILL_SPLIT = re.compile(r"[,;|\u2022\u00b7]|\s{2,}|\s-\s")
_JUNK = {"and", "etc", "others", "other", "basic", "basics", "good", "strong", "excellent", "proficient",
         "familiar", "knowledge", "skills", "tools", "technologies", "languages", "frameworks",
         "fundamentals", "concepts", "experience", "understanding", "working", "hands-on", "relevant",
         "various", "including", "more", "communication", "teamwork", "leadership"}
_SPOKEN = {"english", "hindi", "punjabi", "spanish", "french", "german", "tamil", "telugu", "marathi",
           "bengali", "gujarati", "urdu", "arabic", "chinese", "japanese", "portuguese", "russian"}


def _other_skills(lines: List[str]) -> List[str]:
    out: List[str] = []
    for line in lines:
        head, sep, rest = line.partition(":")
        body = rest if sep and len(head) <= 30 else line
        body = re.sub(r"\([^)]*\)", " ", body)
        for item in _SKILL_SPLIT.split(body):
            item = item.strip(" .:-()[]").lower()
            words = item.split()
            if (2 <= len(item) <= 30 and 1 <= len(words) <= 3 and re.search(r"[a-z]", item)
                    and "@" not in item and "http" not in item
                    and not all(w in _JUNK for w in words) and item not in _SPOKEN
                    and item not in ALIAS_TO_CANON and item not in out):
                out.append(item)
    return out[:15]


_CATEGORY_ROLES = {
    "Backend": "Backend Developer", "Frontend": "Frontend Developer", "Mobile": "Mobile App Developer",
    "Data & AI": "Data Analyst", "Cloud & DevOps": "DevOps Engineer", "Testing/QA": "QA Engineer",
    "Security": "Security Analyst", "Design": "UI/UX Designer", "Product & Delivery": "Product Manager",
    "Marketing": "Digital Marketing Specialist", "Sales & Support": "Sales Executive",
    "Finance": "Financial Analyst", "HR": "HR Executive", "Operations": "Operations Analyst",
}


# ======================= locations =======================
_US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ "
                 "NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
_COUNTRY_KEYS = [k for k in COUNTRY_MAP if len(k) > 3 and k != "remote"]
_DISPLAY = {"usa": "United States", "us": "United States", "uk": "United Kingdom",
            "uae": "United Arab Emirates", "korea": "South Korea"}


def _display_country(key: str) -> str:
    return _DISPLAY.get(key, key.title())


def _locations(header: List[str]) -> Tuple[List[str], List[str]]:
    cities: List[str] = []
    countries: List[str] = []
    for line in header[:10]:
        if len(line) > 160:
            continue
        for seg in re.split(r"[|\u2022\u00b7]", line):
            if "," not in seg or "@" in seg or re.search(r"\d", seg):
                continue
            parts = [p.strip() for p in seg.split(",")]
            if not 2 <= len(parts) <= 3 or any(not re.fullmatch(r"[A-Za-z][A-Za-z.' -]{1,29}", p) for p in parts):
                continue
            last = parts[-1].lower()
            if last in COUNTRY_MAP and last != "remote":
                label = f"{parts[0]}, {_display_country(last)}"
                cities.append(label)
                countries.append(_display_country(last))
            elif parts[-1].isupper() and parts[-1] in _US_STATES:
                cities.append(f"{parts[0]}, {parts[-1]}, United States")
                countries.append("United States")
        low = line.lower()
        for key in _COUNTRY_KEYS:
            if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low):
                countries.append(_display_country(key))
    dedupe = lambda xs: list(dict.fromkeys(xs))       # noqa: E731
    return dedupe(cities), dedupe(countries)


# ======================= main entry =======================
def analyze_resume(text: str) -> dict:
    text = _normalize(text or "")
    lower = text.lower()
    sections = split_sections(text)
    header = sections.get("header", [])
    all_lines = [l for l in text.split("\n") if l]

    # --- role ---
    role = _detect_role(sections)
    seniority = _seniority(role["phrase"]) if role else None

    # --- skills ---
    total = count_skills(lower)
    in_section = count_skills(" ".join(sections.get("skills", [])).lower())
    score = {s: n + (3 if s in in_section else 0) for s, n in total.items()}
    ranked = sorted(score, key=lambda s: (-score[s], s))
    skills = ranked[:30]
    cat_scores: Counter = Counter()
    for s, n in score.items():
        cat_scores[CANON_CATEGORY[s]] += n
    skill_categories = dict(cat_scores.most_common(5))
    other = _other_skills(sections.get("skills", []))

    # --- experience & education ---
    years, computed, stated = _years(sections, lower)
    education, edu_signal = _education(sections, all_lines)
    is_student = edu_signal and (years is None or years < 2)
    levels = _levels(years, seniority, is_student)
    if years is not None:
        max_years: Optional[int] = int(math.ceil(years)) + 2
    else:
        max_years = 2 if is_student else None

    # --- searches ---
    primary = _search_term(role["phrase"]) if role else None
    mapped = [(c, n) for c, n in cat_scores.most_common() if c in _CATEGORY_ROLES]
    top = mapped[0][1] if mapped else 0               # ignore weak signals (one stray "Jira" != Product Manager)
    alts = [_CATEGORY_ROLES[c] for c, n in mapped if n >= max(4, 0.35 * top)]
    if not primary and not alts and skills:
        alts = ["Software Developer"] if any(CANON_CATEGORY[s] == "Programming" for s in skills) else []
    candidates = ([primary] if primary else []) + alts
    uniq: List[str] = []
    for c in candidates:
        if c.lower() not in {u.lower() for u in uniq}:
            uniq.append(c)
    suggested = uniq[0] if uniq else None
    alternatives = uniq[1:4]

    # --- location, identity ---
    cities, countries = _locations(header)
    email, links = _links(text, header)
    summary_lines = sections.get("summary", [])[:3]
    summary = " ".join(summary_lines)[:400] or None
    certs = [l for l in sections.get("certifications", []) if 4 <= len(l) <= 100][:8]

    # --- confidence (lets the UI mark fields as "please check") ---
    role_conf = "low"
    if role:
        role_conf = {"headline": "high", "experience": "medium"}.get(role["source"], "low")
    exp_conf = "low"
    if computed is not None and stated is not None:
        exp_conf = "high" if abs(computed - stated) <= 1 else "medium"
    elif years is not None:
        exp_conf = "medium"
    confidence = {"role": role_conf, "experience": exp_conf,
                  "location": "high" if cities else ("medium" if countries else "low")}

    # --- ready-made request for POST /api/scrape (only non-empty fields) ---
    req: dict = {}
    if suggested:
        req["search_term"] = suggested
    if alternatives:
        req["extra_search_terms"] = alternatives[:2]
    my_skills = (skills + other)[:40]
    if my_skills:
        req["my_skills"] = my_skills
    if levels:
        req["experience_levels"] = levels
    if max_years is not None:
        req["max_experience_years"] = max_years
    if cities:
        req["cities"] = cities[:3]
    elif countries:
        req["countries"] = countries[:3]

    return {
        # original keys (unchanged meaning)
        "suggested_search": suggested,
        "skills": skills,
        "years_experience": years,
        "summary": summary,
        # new
        "name": _name(header),
        "email": email,
        "links": links,
        "seniority": seniority,
        "experience_levels": levels,
        "max_experience_years": max_years,
        "is_student": is_student,
        "education": education,
        "certifications": certs,
        "other_skills": other,
        "skill_categories": skill_categories,
        "alternative_searches": alternatives,
        "locations": {"cities": cities, "countries": countries},
        "confidence": confidence,
        "suggested_request": req,
    }