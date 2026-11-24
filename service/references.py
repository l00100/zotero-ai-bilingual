"""Conservative text-heading detection and local masking of bibliography regions.

Mask before model requests, then restore exact original PDF regions afterwards.
This preserves mixed body/reference pages without translating bibliography text.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re

import pymupdf

PREFIX = r"(?:(?:[IVXLCDM]+|\d+)[.、:\s]+)?"
REFERENCE = re.compile(r"^" + PREFIX + r"(?:references|bibliography|参考文献|參考文獻)\s*[:：]?$", re.I)
APPENDIX = re.compile(r"^" + PREFIX + r"(?:appendix|appendices|supplementary material|附录|附錄)(?:\s+[A-Z0-9]+)?(?:[.:：]\s*[^.]{1,100})?$", re.I)


@dataclass
class ReferencePlan:
    regions: dict[int, list[tuple[float, float, float, float]]]
    start_page: int | None = None


def lines(page):
    result = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                result.append((text, pymupdf.Rect(line["bbox"])))
    return result


def is_two_column(page, text_lines):
    middle = page.rect.x0 + page.rect.width / 2
    counts = Counter()
    for text, box in text_lines:
        if len(text) >= 20 and page.rect.width * .23 < box.width < page.rect.width * .55:
            counts[0 if box.x1 <= middle + 12 else 1 if box.x0 >= middle - 12 else -1] += 1
    return counts[0] >= 3 and counts[1] >= 3


def position(number, box, two_columns, page):
    if not two_columns:
        return number, 0, box.y0
    middle = page.rect.x0 + page.rect.width / 2
    # A centered full-width section heading begins before both columns.
    if box.x0 < middle < box.x1:
        return number, 0, box.y0
    return number, 0 if (box.x0 + box.x1) / 2 < middle else 1, box.y0


def detect_references(document):
    all_lines = [lines(page) for page in document]
    columns = [is_two_column(page, data) for page, data in zip(document, all_lines)]
    candidates = []
    for number, (page, data) in enumerate(zip(document, all_lines)):
        if number < int(len(document) * .4):
            continue
        for text, box in data:
            if REFERENCE.fullmatch(re.sub(r"\s+", " ", text)):
                candidates.append((position(number, box, columns[number], page), box))
    for start, heading in sorted(candidates):
        following = []
        end = None
        for number in range(start[0], len(document)):
            for text, box in all_lines[number]:
                point = position(number, box, columns[number], document[number])
                if point <= start:
                    continue
                if APPENDIX.fullmatch(text):
                    if end is None or point < end:
                        end = point
                following.append((point, text))
        text = "\n".join(t for point, t in sorted(following) if end is None or point < end)
        numbered = len(re.findall(r"(?m)^\s*\[\s*\d+\s*\]", text))
        author_year = len(re.findall(r"\b(?:19|20)\d{2}[a-z]?\b", text))
        if numbered < 2 and not (author_year >= 3 and len(text) >= 300):
            continue  # No reliable bibliography evidence: do not guess.
        regions = {}
        for number in range(start[0], len(document)):
            page = document[number]
            rect = page.rect
            middle = rect.x0 + rect.width / 2
            count = 2 if columns[number] else 1
            for column in range(count):
                top, bottom = rect.y0 + 20, rect.y1 - 25
                if (number, column) < start[:2] or (end and (number, column) > end[:2]):
                    continue
                if (number, column) == start[:2]:
                    top = max(top, heading.y0 - 1)
                if end and (number, column) == end[:2]:
                    bottom = min(bottom, end[2] - 1)
                if bottom <= top:
                    continue
                left = rect.x0 if column == 0 else middle
                right = middle if count == 2 and column == 0 else rect.x1
                regions.setdefault(number, []).append((left, top, right, bottom))
        return ReferencePlan(regions, start[0] + 1)
    return ReferencePlan({})


def selected_indexes(pages, page_count):
    if not pages:
        return set(range(page_count))
    selected = set()
    for part in pages.split(","):
        part = part.strip()
        if "-" in part:
            left, right = part.split("-", 1)
            start, end = int(left or 1), int(right or page_count)
        else:
            start = end = int(part)
        if start < 1 or end < start or end > page_count:
            raise ValueError("翻译页码超出 PDF 范围或格式不正确")
        selected.update(range(start - 1, end))
    return selected


def mask_references(source, output, pages=""):
    with pymupdf.open(source) as document:
        plan = detect_references(document)
        selected = selected_indexes(pages, len(document))
        plan.regions = {number: regions for number, regions in plan.regions.items() if number in selected}
        if not plan.regions:
            return Path(source), plan
        for number, regions in plan.regions.items():
            page = document[number]
            for region in regions:
                page.add_redact_annot(region, fill=(1, 1, 1))
            # Remove only text in the temporary copy. Original paper is untouched.
            page.apply_redactions(images=0, graphics=0, text=0)
        document.save(output, garbage=4, deflate=True)
    return Path(output), plan


def restore_references(source, translated, output, plan):
    with pymupdf.open(source) as original, pymupdf.open(translated) as result:
        if len(original) != len(result):
            raise ValueError("译文页数变化，无法安全恢复原文参考文献")
        for number, regions in plan.regions.items():
            page = result[number]
            for region in regions:
                clip = pymupdf.Rect(region)
                page.draw_rect(clip, color=None, fill=(1, 1, 1), overlay=True)
                page.show_pdf_page(clip, original, number, clip=clip, keep_proportion=False, overlay=True)
                for link in original[number].get_links():
                    if clip.contains(link["from"]) and link.get("kind") in (pymupdf.LINK_URI, pymupdf.LINK_GOTO):
                        copied = {key: value for key, value in link.items() if key not in ("xref", "id")}
                        page.insert_link(copied)
        result.save(output, garbage=4, deflate=True)
