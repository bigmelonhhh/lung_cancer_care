from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib import parse as urlparse
from urllib import request as urlrequest


DEFAULT_SAMPLE_HTML = Path("docs/crawler/example1.html")
DEFAULT_CSV_PATH = Path("docs/crawler/category_drugs.csv")
DEFAULT_SLEEP_SECONDS = 3.0
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CSV_HEADERS = ["名称", "唯名称（名称+厂名）", "商品名", "厂商名", "分类名"]


@dataclass(frozen=True)
class ParsedDrugItem:
    base_name: str
    trade_name: str
    manufacturer: str

    @property
    def full_name(self) -> str:
        if self.base_name and self.manufacturer:
            return f"{self.base_name} - {self.manufacturer}"
        return self.base_name or self.manufacturer

    @property
    def description(self) -> str:
        if self.manufacturer:
            return f"厂商：{self.manufacturer}"
        return ""


def _normalize_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split()).strip()


def _split_name_and_manufacturer(title: str) -> Tuple[str, str]:
    title = _normalize_text(title)
    if " - " in title:
        base_name, manufacturer = title.rsplit(" - ", 1)
        return base_name.strip(), manufacturer.strip()
    return title.strip(), ""


def _base_name_from_unique(unique_name: str, manufacturer: str) -> str:
    base_name, parsed_manufacturer = _split_name_and_manufacturer(unique_name)
    if parsed_manufacturer or manufacturer:
        return base_name
    return unique_name.strip()


def _build_page_url(category_url: str, page: int) -> str:
    parts = urlparse.urlsplit(category_url)
    query = urlparse.parse_qs(parts.query, keep_blank_values=True)
    query["page"] = [str(page)]
    new_query = urlparse.urlencode(query, doseq=True)
    return urlparse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
    )


def _extract_max_page(html: str) -> int:
    pages = [int(value) for value in re.findall(r"[?&]page=(\d+)", html)]
    return max(pages, default=1)


def _extract_total_count(html: str) -> int:
    match = re.search(r"page_category-header-count[^>]*>(\d+)<", html)
    if match:
        return int(match.group(1))
    match = re.search(r"共有药品[^<]*<span[^>]*>(\d+)</span>", html)
    if match:
        return int(match.group(1))
    return 0


def _determine_total_pages(html: str, items_per_page: int) -> int:
    total_pages = _extract_max_page(html)
    total_count = _extract_total_count(html)
    if total_count and items_per_page:
        computed = (total_count + items_per_page - 1) // items_per_page
        if computed > total_pages:
            total_pages = computed
    return max(total_pages, 1)


def _fetch_html(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    request = urlrequest.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlrequest.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="ignore")


def _get_attr(attrs: Iterable[Tuple[str, Optional[str]]], name: str) -> str:
    for key, value in attrs:
        if key == name:
            return value or ""
    return ""


def _class_contains(attrs: Iterable[Tuple[str, Optional[str]]], needle: str) -> bool:
    class_attr = _get_attr(attrs, "class")
    return needle in (class_attr or "")


class _DrugCategoryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: List[ParsedDrugItem] = []
        self._in_drug_item = False
        self._in_h3 = False
        self._in_cn_p = False
        self._in_span = False
        self._span_index = 0
        self._current_title_parts: List[str] = []
        self._current_title = ""
        self._current_trade_name = ""
        self._current_manufacturer = ""
        self._span_text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "li" and _class_contains(attrs, "DrugsItem_drugs-item"):
            self._in_drug_item = True
            self._reset_current()
            return

        if not self._in_drug_item:
            return

        if tag == "h3" and _class_contains(attrs, "DrugsItem_drugs-item-name"):
            self._in_h3 = True
            return

        if tag == "p" and _class_contains(attrs, "DrugsItem_drugs-item-cnName"):
            self._in_cn_p = True
            self._span_index = 0
            return

        if tag == "span" and self._in_cn_p:
            self._in_span = True
            self._span_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._current_title_parts.append(data)
        if self._in_span:
            self._span_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            self._in_h3 = False
            self._current_title = _normalize_text("".join(self._current_title_parts))
            return

        if tag == "span" and self._in_span:
            text = _normalize_text("".join(self._span_text_parts))
            if self._span_index == 0 and not self._current_trade_name:
                self._current_trade_name = text
            elif self._span_index == 1 and not self._current_manufacturer:
                self._current_manufacturer = text
            self._span_index += 1
            self._in_span = False
            return

        if tag == "p" and self._in_cn_p:
            self._in_cn_p = False
            return

        if tag == "li" and self._in_drug_item:
            self._finalize_current()
            self._in_drug_item = False

    def _reset_current(self) -> None:
        self._current_title_parts = []
        self._current_title = ""
        self._current_trade_name = ""
        self._current_manufacturer = ""
        self._span_index = 0
        self._span_text_parts = []

    def _finalize_current(self) -> None:
        title = self._current_title or _normalize_text("".join(self._current_title_parts))
        base_name, h3_manufacturer = _split_name_and_manufacturer(title)
        manufacturer = self._current_manufacturer or h3_manufacturer
        item = ParsedDrugItem(
            base_name=base_name or title,
            trade_name=self._current_trade_name,
            manufacturer=manufacturer,
        )
        if item.full_name:
            self.items.append(item)


class _CategoryNameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.category_name = ""
        self._in_header = False
        self._header_depth = 0
        self._in_h2 = False
        self._h2_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "div" and _class_contains(attrs, "page_category-header"):
            self._in_header = True
            self._header_depth = 1
            return

        if self._in_header and tag == "div":
            self._header_depth += 1

        if self._in_header and tag == "h2":
            self._in_h2 = True
            self._h2_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._in_h2:
            self._in_h2 = False
            if not self.category_name:
                self.category_name = _normalize_text("".join(self._h2_parts))

        if self._in_header and tag == "div":
            self._header_depth -= 1
            if self._header_depth <= 0:
                self._in_header = False


def extract_category_name(html: str) -> str:
    parser = _CategoryNameParser()
    parser.feed(html)
    parser.close()
    if parser.category_name:
        return parser.category_name

    match = re.search(r"<h2[^>]*>(.*?)</h2>", html, re.S)
    if not match:
        return ""
    text = re.sub(r"<[^>]+>", "", match.group(1))
    return _normalize_text(text)


def parse_category_html(html: str) -> List[ParsedDrugItem]:
    parser = _DrugCategoryParser()
    parser.feed(html)
    parser.close()
    return parser.items


def parse_category_file(html_path: str | Path = DEFAULT_SAMPLE_HTML) -> List[ParsedDrugItem]:
    html = Path(html_path).read_text(encoding="utf-8")
    return parse_category_html(html)


def _print_items(items: Iterable[ParsedDrugItem]) -> None:
    for item in items:
       pass


def print_category_file(html_path: str | Path = DEFAULT_SAMPLE_HTML) -> List[ParsedDrugItem]:
    items = parse_category_file(html_path)
    _print_items(items)
    return items


def iter_category_page_html(
    category_url: str,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_pages: int | None = None,
) -> Iterable[str]:
    first_url = _build_page_url(category_url, 1)
    html = _fetch_html(first_url)
    items_per_page = len(parse_category_html(html))
    total_pages = _determine_total_pages(html, items_per_page)
    if max_pages is not None:
        total_pages = min(total_pages, max_pages)
    yield html

    for page in range(2, total_pages + 1):
        time.sleep(sleep_seconds)
        html = _fetch_html(_build_page_url(category_url, page))
        yield html


def iter_category_pages(
    category_url: str,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_pages: int | None = None,
) -> Iterable[List[ParsedDrugItem]]:
    for html in iter_category_page_html(
        category_url, sleep_seconds=sleep_seconds, max_pages=max_pages
    ):
        yield parse_category_html(html)


def parse_category_url_all(
    category_url: str,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_pages: int | None = None,
) -> List[ParsedDrugItem]:
    items: List[ParsedDrugItem] = []
    for page_items in iter_category_pages(
        category_url, sleep_seconds=sleep_seconds, max_pages=max_pages
    ):
        items.extend(page_items)
    return items


def print_category_url_all(
    category_url: str,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_pages: int | None = None,
) -> List[ParsedDrugItem]:
    items: List[ParsedDrugItem] = []
    for page_items in iter_category_pages(
        category_url, sleep_seconds=sleep_seconds, max_pages=max_pages
    ):
        _print_items(page_items)
        items.extend(page_items)
    return items


def write_category_csv(
    category_urls: Iterable[str],
    csv_path: str | Path = DEFAULT_CSV_PATH,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_pages: int | None = None,
) -> dict:
    csv_path = Path(csv_path)
    existing_rows = _load_csv_rows(csv_path)

    base_counts: dict[tuple[str, str], int] = {}
    for row in existing_rows:
        base_name = _base_name_from_unique(
            row.get("唯名称（名称+厂名）", ""), row.get("厂商名", "")
        )
        category = row.get("分类名", "")
        key = (category, base_name)
        base_counts[key] = base_counts.get(key, 0) + 1

    new_items: List[tuple[ParsedDrugItem, str]] = []
    for category_url in category_urls:
        category_name = ""
        for html in iter_category_page_html(
            category_url, sleep_seconds=sleep_seconds, max_pages=max_pages
        ):
            if not category_name:
                category_name = extract_category_name(html) or "未知分类"
            items = parse_category_html(html)
            for item in items:
                new_items.append((item, category_name))
                key = (category_name, item.base_name)
                base_counts[key] = base_counts.get(key, 0) + 1

    updated_rows = []
    for row in existing_rows:
        base_name = _base_name_from_unique(
            row.get("唯名称（名称+厂名）", ""), row.get("厂商名", "")
        )
        category = row.get("分类名", "")
        display_name = base_name
        if base_counts.get((category, base_name), 0) > 1:
            display_name = row.get("唯名称（名称+厂名）", display_name)
        row["名称"] = display_name
        updated_rows.append(row)

    existing_keys = {
        (row.get("名称", ""), row.get("厂商名", ""), row.get("分类名", ""))
        for row in updated_rows
    }

    added = 0
    skipped = 0
    for item, category_name in new_items:
        base_name = item.base_name
        display_name = base_name
        if base_counts.get((category_name, base_name), 0) > 1:
            display_name = item.full_name
        row = {
            "名称": display_name,
            "唯名称（名称+厂名）": item.full_name,
            "商品名": item.trade_name,
            "厂商名": item.manufacturer,
            "分类名": category_name,
        }
        key = (row["名称"], row["厂商名"], row["分类名"])
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)
        updated_rows.append(row)
        added += 1

    _write_csv_rows(csv_path, updated_rows)
    return {
        "added": added,
        "skipped": skipped,
        "existing": len(existing_rows),
        "total_rows": len(updated_rows),
    }


def save_medications(items: Iterable[ParsedDrugItem]) -> dict:
    from core.models import Medication

    created = 0
    updated = 0
    skipped = 0
    total = 0
    for item in items:
        total += 1
        full_name = item.full_name.strip()
        if not full_name:
            skipped += 1
            continue

        defaults = {
            "trade_names": item.trade_name.strip(),
            "description": item.description.strip(),
        }

        obj, created_flag = Medication.objects.get_or_create(
            name=full_name,
            defaults=defaults,
        )
        if created_flag:
            created += 1
            continue

        update_fields = []
        trade_name = defaults["trade_names"]
        if trade_name and not obj.trade_names:
            obj.trade_names = trade_name
            update_fields.append("trade_names")

        description_line = defaults["description"]
        if description_line:
            if obj.description:
                if description_line not in obj.description:
                    obj.description = f"{obj.description}\n{description_line}"
                    update_fields.append("description")
            else:
                obj.description = description_line
                update_fields.append("description")

        if update_fields:
            obj.save(update_fields=update_fields)
            updated += 1

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": total,
    }


def save_category_file(
    html_path: str | Path = DEFAULT_SAMPLE_HTML,
) -> dict:
    return save_medications(parse_category_file(html_path))


def save_category_url(
    category_url: str,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    max_pages: int | None = None,
) -> dict:
    items = parse_category_url_all(
        category_url, sleep_seconds=sleep_seconds, max_pages=max_pages
    )
    return save_medications(items)


def _load_csv_rows(csv_path: Path) -> List[dict]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            rows.append({key: (value or "").strip() for key, value in row.items()})
        return rows


def _write_csv_rows(csv_path: Path, rows: List[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in CSV_HEADERS})
