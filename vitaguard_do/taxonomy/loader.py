from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import re
import unicodedata

import yaml


def normalize_alias(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class TaxonomyItem:
    category: str
    id: str
    label: str
    aliases: tuple[str, ...]
    description: str | None = None


class TaxonomyRegistry:
    def __init__(self, items: Iterable[TaxonomyItem]):
        self.items = list(items)
        self.by_id: dict[tuple[str, str], TaxonomyItem] = {}
        self.alias_index: dict[tuple[str, str], TaxonomyItem] = {}
        self._validate_and_index()

    def _validate_and_index(self):
        errors: list[str] = []
        for item in self.items:
            key = (item.category, item.id)
            if key in self.by_id:
                errors.append(f"duplicate id in {item.category}: {item.id}")
            self.by_id[key] = item

            if not item.id or not item.label:
                errors.append(f"empty id/label in {item.category}")
            if not item.aliases:
                errors.append(f"item without aliases: {item.category}/{item.id}")

            for alias in (item.label, *item.aliases):
                norm = normalize_alias(alias)
                if not norm:
                    errors.append(f"empty normalized alias: {item.category}/{item.id}")
                    continue
                akey = (item.category, norm)
                prior = self.alias_index.get(akey)
                if prior and prior.id != item.id:
                    errors.append(
                        f"alias collision in {item.category}: '{alias}' -> {prior.id} and {item.id}"
                    )
                else:
                    self.alias_index[akey] = item

        if errors:
            raise ValueError("Invalid taxonomy:\n- " + "\n- ".join(errors))

    def resolve(self, category: str, text: str) -> TaxonomyItem | None:
        return self.alias_index.get((category, normalize_alias(text)))

    def has_id(self, category: str, canonical_id: str) -> bool:
        return (category, canonical_id) in self.by_id

    def get_item(self, category: str, canonical_id: str | None) -> TaxonomyItem | None:
        if not canonical_id:
            return None
        return self.by_id.get((category, canonical_id))

    def recovery_terms(self, category: str, canonical_id: str | None, original_name: str | None = None) -> list[str]:
        # Taxonomy terms come first because they are the stable semantic anchors.
        # The insurer-specific original title is still retained as a fallback.
        terms: list[str] = []
        item = self.get_item(category, canonical_id)
        if item is not None:
            terms.extend([item.label, *item.aliases])
        if original_name:
            terms.append(original_name)

        normalized_terms: list[tuple[str, str]] = []
        seen: set[str] = set()
        for term in terms:
            norm = normalize_alias(term)
            if norm and norm not in seen:
                seen.add(norm)
                normalized_terms.append((term, norm))
        if not normalized_terms:
            return []

        # Evidence recovery must be stricter than taxonomy normalization, but the
        # old 60% length cutoff discarded useful formal headings such as
        # "Custos de Investigacao" when a longer alias also existed. 40% keeps
        # specific two/three-word headings while still dropping very generic terms.
        max_len = max(len(norm) for _, norm in normalized_terms)
        min_len = max(6, int(max_len * 0.40))
        return [term for term, norm in normalized_terms if len(norm) >= min_len]


def load_taxonomies(base_dir: str | Path | None = None) -> TaxonomyRegistry:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent
    base = Path(base_dir)
    items: list[TaxonomyItem] = []
    for path in sorted(base.glob("*.yaml")):
        category = path.stem
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("items", []):
            items.append(TaxonomyItem(
                category=category,
                id=str(raw["id"]),
                label=str(raw["label"]),
                aliases=tuple(str(x) for x in raw.get("aliases", [])),
                description=raw.get("description"),
            ))
    return TaxonomyRegistry(items)
