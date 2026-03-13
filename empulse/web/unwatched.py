import logging
import re
from urllib.parse import quote

from fastapi import Request

from empulse import database
from empulse.db import libraries as libraries_db, stats as stats_db

logger = logging.getLogger("empulse.unwatched")

DEFAULT_PAGE_SIZE = 48
MAX_PAGE_SIZE = 100
CATALOG_PAGE_SIZE = 200
VALID_SORTS = {"name_asc", "name_desc", "year_desc", "year_asc", "added_desc"}
LIBRARY_ITEM_TYPES = {
    "movies": ("Movie", "Movie", "Movies", "movie"),
    "tvshows": ("Series", "Episode", "TV Shows", "series"),
    "music": ("Audio", "Audio", "Music", "track"),
}
DEFAULT_ITEM_TYPES = "Movie,Series,Audio"


def _normalize_page(page: int) -> int:
    return max(1, page)


def _normalize_page_size(page_size: int) -> int:
    return max(1, min(page_size, MAX_PAGE_SIZE))


def _normalize_search(search: str) -> str:
    return (search or "").strip()[:100]


def _normalize_library_id(library_id: str) -> str:
    return (library_id or "").strip()[:128]


def _normalize_sort(sort: str) -> str:
    return sort if sort in VALID_SORTS else "name_asc"


def _canonical_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").casefold())


def _item_signature(name: str, year: object, premiered: str, catalog_type: str) -> tuple[str, object, str, str]:
    return (_canonical_name(name), year or "", premiered or "", catalog_type or "")


def _sort_items(items: list[dict], sort: str) -> list[dict]:
    if sort == "name_desc":
        return sorted(items, key=lambda item: item["name"].casefold(), reverse=True)
    if sort == "year_desc":
        return sorted(
            items,
            key=lambda item: (item.get("year") or 0, item["name"].casefold()),
            reverse=True,
        )
    if sort == "year_asc":
        return sorted(
            items,
            key=lambda item: (
                item.get("year") if item.get("year") is not None else 999999,
                item["name"].casefold(),
            ),
        )
    if sort == "added_desc":
        return sorted(
            items,
            key=lambda item: ((item.get("date_created") or ""), item["name"].casefold()),
            reverse=True,
        )
    return sorted(items, key=lambda item: item["name"].casefold())


def _link_for_item(item: dict) -> str:
    if item["catalog_type"] == "Series":
        return f"/item/{item['item_id']}?type=series&name={quote(item['name'])}"
    return f"/item/{item['item_id']}"


def _prefer_item(candidate: dict, current: dict | None) -> dict:
    if current is None:
        return candidate
    current_score = (
        len(current.get("overview") or ""),
        bool(current.get("premiere_date")),
        bool(current.get("date_created")),
    )
    candidate_score = (
        len(candidate.get("overview") or ""),
        bool(candidate.get("premiere_date")),
        bool(candidate.get("date_created")),
    )
    return candidate if candidate_score > current_score else current


async def _load_library_scope(db, library_id: str) -> dict:
    libraries = await libraries_db.get_all_libraries(db)
    selected = next((lib for lib in libraries if lib.get("emby_library_id") == library_id), None)
    if selected:
        library_type = selected.get("library_type") or ""
        mapping = LIBRARY_ITEM_TYPES.get(library_type)
        if mapping:
            return {
                "include_item_types": mapping[0],
                "history_item_type": mapping[1],
                "scope_label": selected.get("name") or mapping[2],
                "empty_label": mapping[3],
                "library": selected,
            }
    return {
        "include_item_types": DEFAULT_ITEM_TYPES,
        "history_item_type": "",
        "scope_label": "All libraries",
        "empty_label": "items",
        "library": selected,
    }


async def fetch_unwatched_items(
    request: Request,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    search: str = "",
    sort: str = "name_asc",
    library_id: str = "",
) -> dict:
    normalized_page = _normalize_page(page)
    normalized_page_size = _normalize_page_size(page_size)
    normalized_search = _normalize_search(search)
    normalized_sort = _normalize_sort(sort)
    normalized_library_id = _normalize_library_id(library_id)

    emby_client = getattr(request.app.state, "emby_client", None)
    if not emby_client:
        return {
            "available": False,
            "items": [],
            "total": 0,
            "shown": 0,
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total_pages": 0,
            "search": normalized_search,
            "sort": normalized_sort,
            "library_id": normalized_library_id,
            "scope_label": "All libraries",
            "empty_label": "items",
            "error": "",
        }

    db = database.get_db()
    scope = await _load_library_scope(db, normalized_library_id)

    watched_ids: set[str] = set()
    watched_names: set[str] = set()
    if scope["history_item_type"]:
        watched = await stats_db.get_watched_item_keys(db, scope["history_item_type"])
        watched_ids = watched["series_ids"]
        watched_names = {_canonical_name(name) for name in watched["series_names"]}
    else:
        for history_item_type in {"Movie", "Episode", "Audio"}:
            watched = await stats_db.get_watched_item_keys(db, history_item_type)
            watched_ids.update(watched["series_ids"])
            watched_names.update(_canonical_name(name) for name in watched["series_names"])

    matched_by_key: dict[tuple[str, object, str, str], dict] = {}
    start_index = 0

    try:
        while True:
            page_data = await emby_client.get_catalog_page(
                limit=CATALOG_PAGE_SIZE,
                start_index=start_index,
                search=normalized_search,
                parent_id=normalized_library_id,
                include_item_types=scope["include_item_types"],
            )
            catalog_items = page_data.get("items", [])
            total = int(page_data.get("total", 0) or 0)
            if not catalog_items:
                break

            start_index += len(catalog_items)
            for item in catalog_items:
                item_id = str(item.get("Id", "")).strip()
                name = (item.get("Name") or "").strip()
                catalog_type = (item.get("Type") or "").strip()
                premiere_date = (item.get("PremiereDate") or "")[:10]
                signature = _item_signature(name, item.get("ProductionYear"), premiere_date, catalog_type)
                if item_id and item_id in watched_ids:
                    continue
                if name and _canonical_name(name) in watched_names:
                    continue

                candidate = {
                    "item_id": item_id,
                    "name": name or "Unknown item",
                    "year": item.get("ProductionYear"),
                    "overview": (item.get("Overview") or "").strip(),
                    "premiere_date": premiere_date,
                    "date_created": (item.get("DateCreated") or "")[:10],
                    "poster_id": item_id,
                    "catalog_type": catalog_type,
                    "link": _link_for_item(
                        {
                            "item_id": item_id,
                            "name": name or "Unknown item",
                            "catalog_type": catalog_type,
                        }
                    ),
                }
                matched_by_key[signature] = _prefer_item(candidate, matched_by_key.get(signature))

            if (total and start_index >= total) or len(catalog_items) < CATALOG_PAGE_SIZE:
                break
    except Exception as exc:
        logger.error("Unwatched items fetch failed: %s", exc)
        return {
            "available": True,
            "items": [],
            "total": 0,
            "shown": 0,
            "page": normalized_page,
            "page_size": normalized_page_size,
            "total_pages": 0,
            "search": normalized_search,
            "sort": normalized_sort,
            "library_id": normalized_library_id,
            "scope_label": scope["scope_label"],
            "empty_label": scope["empty_label"],
            "error": "Unable to load items from Emby right now.",
        }

    sorted_items = _sort_items(list(matched_by_key.values()), normalized_sort)
    total_items = len(sorted_items)
    total_pages = (total_items + normalized_page_size - 1) // normalized_page_size
    current_page = min(normalized_page, max(1, total_pages)) if total_items else 1
    start = (current_page - 1) * normalized_page_size
    end = start + normalized_page_size
    page_items = sorted_items[start:end]

    return {
        "available": True,
        "items": page_items,
        "total": total_items,
        "shown": len(page_items),
        "page": current_page,
        "page_size": normalized_page_size,
        "total_pages": total_pages,
        "search": normalized_search,
        "sort": normalized_sort,
        "library_id": normalized_library_id,
        "scope_label": scope["scope_label"],
        "empty_label": scope["empty_label"],
        "error": "",
    }
