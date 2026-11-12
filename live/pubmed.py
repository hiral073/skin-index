import os
import re
import threading
import time

import requests

# PubMed through NCBI's free E-utilities (no API key): esearch finds the IDs, esummary gives the
# details. NCBI asks scripts to make no more than 3 requests per second and to send `tool` and
# `email`. The email is read from the NCBI_EMAIL environment variable when a search is made; it is
# never written in the code or the repository, and with no variable set no email is sent.
PUBMED_CONFIG = {
    "esearch_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
    "esummary_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
    "timeout_seconds": 5,
    "min_gap_seconds": 0.4,           # at least this long between any two requests (under 3 per second)
    "retry_after_cap_seconds": 2,     # a 429 is retried once, after at most this long
    "failure_memory_seconds": 10,     # after a failure, do not call again for this long
    "tool": "skin-index",
    "show": 10,                       # papers listed
    "fetch_for_reviews": 20,          # reviews only: look at this many, keep the real reviews
    "skin_filter": "skin",            # every search is "<ingredient> AND skin"
    "review_filter": "(review[pt] OR systematic review[pt])",
}

REVIEW_TYPES = {"Review", "Systematic Review"}
# Types are shown in this order (then the rest alphabetically); the generic one goes last
TYPE_PRIORITY = ["Systematic Review", "Meta-Analysis", "Review", "Randomized Controlled Trial", "Clinical Trial",
                 "Comparative Study", "Observational Study", "Case Reports"]
GENERIC_TYPE = "Journal Article"

_clock = time.monotonic          # tests replace these so no test really waits
_sleep = time.sleep
_lock = threading.Lock()
_last_request = None             # _clock() of the last request made
_failure = None                  # (until, message) after a failure


class PubmedError(Exception):
    """PubMed could not be reached or its answer could not be used."""


def reset_state():
    global _last_request, _failure
    _last_request = _failure = None


def _wait_turn():
    """Block until at least min_gap_seconds have passed since the last request (any thread)."""
    global _last_request
    with _lock:
        if _last_request is not None:
            wait = _last_request + PUBMED_CONFIG["min_gap_seconds"] - _clock()
            if wait > 0:
                _sleep(wait)
        _last_request = _clock()


EMAIL_VARIABLE = "NCBI_EMAIL"
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def contact_email():
    """The contact email from the NCBI_EMAIL environment variable, or None when it is unset, blank or not an address."""
    value = os.environ.get(EMAIL_VARIABLE, "").strip()
    return value if _EMAIL.fullmatch(value) else None


def _base_params():
    params = {"tool": PUBMED_CONFIG["tool"]}
    email = contact_email()
    if email:
        params["email"] = email
    return params


def _get_json(url, params):
    response = None
    for attempt in (1, 2):
        _wait_turn()
        try:
            response = requests.get(url, params={**_base_params(), **params},
                                    timeout=PUBMED_CONFIG["timeout_seconds"])
        except requests.RequestException as exc:
            raise PubmedError(f"Could not reach PubMed: {exc}") from exc
        if getattr(response, "status_code", 200) == 429 and attempt == 1:
            try:
                delay = float(response.headers.get("Retry-After", 1))
            except (TypeError, ValueError):
                delay = 1.0
            _sleep(min(max(delay, 0), PUBMED_CONFIG["retry_after_cap_seconds"]))
            continue
        break
    try:
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PubmedError(f"Could not reach PubMed: {exc}") from exc
    if not isinstance(data, dict):
        raise PubmedError("PubMed sent a reply we could not read.")
    return data


def _text(value):
    if not isinstance(value, str):
        return None
    # drop only simple formatting tags (<i>, <sub> ...); anything else is left for the page to escape
    value = re.sub(r"\s+", " ", re.sub(r"</?(?:i|b|u|em|strong|sub|sup)>", "", value, flags=re.I)).strip()
    return value or None


def _types(raw):
    """Types to show: the informative ones first, 'Journal Article' only when it is all there is."""
    kept = [t for t in (raw if isinstance(raw, list) else []) if isinstance(t, str) and t.strip()]
    kept = [t for t in kept if not t.startswith("Research Support")]
    informative = [t for t in kept if t != GENERIC_TYPE]
    if not informative:
        return [GENERIC_TYPE] if GENERIC_TYPE in kept else []
    rank = {name: i for i, name in enumerate(TYPE_PRIORITY)}
    return sorted(informative, key=lambda t: (rank.get(t, len(rank)), t))


def _paper(uid, item):
    """One paper as {"pmid", "title", "journal", "year", "types", "all_types", "url"}, or None if unusable."""
    if not isinstance(item, dict) or not isinstance(uid, str) or not uid.isdigit():
        return None
    title = _text(item.get("title"))
    if title is None:
        return None
    title = title.rstrip(".")
    year = None
    for field in ("pubdate", "epubdate"):
        match = re.search(r"\b(?:19|20)\d{2}\b", item.get(field) or "") if isinstance(item.get(field), str) else None
        if match:
            year = int(match.group())
            break
    raw_types = item.get("pubtype") if isinstance(item.get("pubtype"), list) else []
    return {
        "pmid": uid, "title": title,
        "journal": _text(item.get("fulljournalname")) or _text(item.get("source")),
        "year": year, "types": _types(raw_types),
        "all_types": [t for t in raw_types if isinstance(t, str)],
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
    }


def search_pubmed(term, reviews_only=False):
    """The most relevant papers for "<term> AND skin": [{"pmid", "title", "journal", "year", "types", "url"}].

    `term` is already cleaned text. With reviews_only, PubMed's review filter is added and only
    papers whose types include Review or Systematic Review are kept (PubMed's filter lets a few
    other types through). Returns [] when nothing matches; raises PubmedError if PubMed fails.
    """
    global _failure
    if _failure and _clock() < _failure[0]:
        raise PubmedError(_failure[1])
    try:
        return _search(term, reviews_only)
    except PubmedError as exc:
        _failure = (_clock() + PUBMED_CONFIG["failure_memory_seconds"], str(exc))
        raise


def _search(term, reviews_only):
    query = f"{term} AND {PUBMED_CONFIG['skin_filter']}"
    if reviews_only:
        query += f" AND {PUBMED_CONFIG['review_filter']}"
    retmax = PUBMED_CONFIG["fetch_for_reviews"] if reviews_only else PUBMED_CONFIG["show"]
    found = _get_json(PUBMED_CONFIG["esearch_url"], {
        "db": "pubmed", "term": query, "retmax": retmax, "retmode": "json", "sort": "relevance",
    })
    result = found.get("esearchresult")
    ids = result.get("idlist") if isinstance(result, dict) else None
    if not isinstance(ids, list):
        raise PubmedError("PubMed sent a search reply we could not read.")   # no match is an empty idlist, not a missing one
    ids = [i for i in ids if isinstance(i, str) and i.isdigit()]
    if not ids:
        return []
    summary = _get_json(PUBMED_CONFIG["esummary_url"], {
        "db": "pubmed", "id": ",".join(ids), "retmode": "json",
    })
    records = summary.get("result")
    if not isinstance(records, dict):
        raise PubmedError("PubMed sent a details reply we could not read.")
    papers = [p for p in (_paper(uid, records.get(uid)) for uid in ids) if p]       # keeps PubMed's relevance order
    if reviews_only:
        papers = [p for p in papers if REVIEW_TYPES & set(p["all_types"])]
    for paper in papers:
        del paper["all_types"]
    return papers[:PUBMED_CONFIG["show"]]
