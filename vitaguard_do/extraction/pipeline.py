from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from vitaguard_do.ingestion.models import IngestedDocument
from vitaguard_do.models.schema import PolicyRecord
from vitaguard_do.taxonomy.loader import TaxonomyRegistry, load_taxonomies

from .assembler import assemble_policy
from .models import (
    ClausesExtraction,
    CoreExtraction,
    CoveragesExtensionsExtraction,
    DefinitionsExtraction,
    ExclusionsExtraction,
    RiskExtraction,
    SemanticExtraction,
    StructuredExtractionRun,
)
from .prompts import (
    clauses_prompt,
    core_prompt,
    coverages_extensions_prompt,
    definitions_prompt,
    exclusions_prompt,
    risk_prompt,
    semantic_prompt,
)
from .provider import StructuredLLMProvider
from .selector import (
    detect_risk_candidates,
    detect_semantic_candidates,
    render_chunks_for_prompt,
    select_chunks,
    select_risk_subchunks,
    select_semantic_subchunks,
)


S = TypeVar("S", bound=BaseModel)
PROJECT_VERSION = "0.5B.5"


class StructuredExtractionPipeline:
    def __init__(
        self,
        provider: StructuredLLMProvider,
        *,
        registry: TaxonomyRegistry | None = None,
        output_dir: str | Path = "outputs/structured",
    ):
        self.provider = provider
        self.registry = registry or load_taxonomies()
        self.output_dir = Path(output_dir)

    def cache_path(self, document: IngestedDocument) -> Path:
        return self.output_dir / f"{Path(document.source_name).stem}.structured.json"

    def stage_cache_path(self, document: IngestedDocument, stage: str) -> Path:
        return (
            self.output_dir
            / "_stages"
            / f"{Path(document.source_name).stem}.{stage}.json"
        )

    def _load_stage_cache(
        self,
        document: IngestedDocument,
        stage: str,
        schema: type[S],
    ) -> S | None:
        path = self.stage_cache_path(document, stage)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("document_id") != document.document_id:
                return None
            return schema.model_validate(raw["payload"])
        except Exception:
            return None

    def _save_stage_cache(
        self,
        document: IngestedDocument,
        stage: str,
        value: BaseModel,
    ) -> None:
        path = self.stage_cache_path(document, stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "document_id": document.document_id,
            "source_name": document.source_name,
            "stage": stage,
            "payload": value.model_dump(mode="json"),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _extract_stage(
        self,
        *,
        document: IngestedDocument,
        stage: str,
        schema: type[S],
        prompt: str,
        use_cache: bool,
        force: bool,
    ) -> S:
        if use_cache and not force:
            cached = self._load_stage_cache(document, stage, schema)
            if cached is not None:
                print(f"[CACHE LLM] {Path(document.source_name).stem} / {stage}")
                return cached

        print(f"[LLM] {Path(document.source_name).stem} / {stage}")
        result = self.provider.generate_structured(prompt, schema)
        # Save immediately. If a later stage hits a quota limit or the runtime
        # disconnects, successful calls are not lost.
        self._save_stage_cache(document, stage, result)
        return result

    def extract(
        self,
        document: IngestedDocument,
        *,
        use_cache: bool = True,
        force: bool = False,
    ) -> tuple[PolicyRecord, StructuredExtractionRun]:
        cache = self.cache_path(document)
        if use_cache and cache.exists() and not force:
            run = StructuredExtractionRun.from_json_file(cache)
            if run.document_id == document.document_id and run.project_version == PROJECT_VERSION:
                print(f"[CACHE FINAL] {Path(document.source_name).stem}")
                return PolicyRecord.model_validate(run.policy_json), run

        selected_core = select_chunks(document, "core", registry=self.registry)
        long_document = document.page_count >= 25
        if long_document:
            selected_risk_coverages_extensions = select_risk_subchunks(
                document, "coverages_extensions", registry=self.registry
            )
            selected_risk_exclusions = select_risk_subchunks(
                document, "exclusions", registry=self.registry
            )
            selected_definitions = select_semantic_subchunks(
                document, "definitions", registry=self.registry
            )
            selected_clauses = select_semantic_subchunks(
                document, "clauses", registry=self.registry
            )
        else:
            selected_risk = select_chunks(document, "risk", registry=self.registry)
            selected_semantic = select_chunks(document, "semantic", registry=self.registry)
            selected_definitions = selected_semantic
            selected_clauses = selected_semantic

        core = self._extract_stage(
            document=document,
            stage="core",
            schema=CoreExtraction,
            prompt=core_prompt(render_chunks_for_prompt(selected_core), self.registry, long_document=long_document),
            use_cache=use_cache,
            force=force,
        )
        if long_document:
            risk_ce_candidates = detect_risk_candidates(
                selected_risk_coverages_extensions,
                "coverages_extensions",
                registry=self.registry,
            )
            risk_exclusion_candidates = detect_risk_candidates(
                selected_risk_exclusions,
                "exclusions",
                registry=self.registry,
            )
            risk_ce = self._extract_stage(
                document=document,
                stage="risk_coverages_extensions",
                schema=CoveragesExtensionsExtraction,
                prompt=coverages_extensions_prompt(
                    render_chunks_for_prompt(selected_risk_coverages_extensions),
                    self.registry,
                    long_document=True,
                    required_candidates=risk_ce_candidates,
                ),
                use_cache=use_cache,
                force=force,
            )
            risk_ex = self._extract_stage(
                document=document,
                stage="risk_exclusions",
                schema=ExclusionsExtraction,
                prompt=exclusions_prompt(
                    render_chunks_for_prompt(selected_risk_exclusions),
                    self.registry,
                    long_document=True,
                    required_candidates=risk_exclusion_candidates,
                ),
                use_cache=use_cache,
                force=force,
            )
            risk = RiskExtraction(
                coverages=risk_ce.coverages,
                extensions=risk_ce.extensions,
                exclusions=risk_ex.exclusions,
                warnings=[*risk_ce.warnings, *risk_ex.warnings],
            )
        else:
            risk = self._extract_stage(
                document=document,
                stage="risk",
                schema=RiskExtraction,
                prompt=risk_prompt(render_chunks_for_prompt(selected_risk), self.registry, long_document=False),
                use_cache=use_cache,
                force=force,
            )

        if long_document:
            definition_candidates = detect_semantic_candidates(
                selected_definitions, "definitions", registry=self.registry
            )
            clause_candidates = detect_semantic_candidates(
                selected_clauses, "clauses", registry=self.registry
            )
            definitions_part = self._extract_stage(
                document=document,
                stage="semantic_definitions",
                schema=DefinitionsExtraction,
                prompt=definitions_prompt(
                    render_chunks_for_prompt(selected_definitions),
                    self.registry,
                    long_document=True,
                    required_candidates=definition_candidates,
                ),
                use_cache=use_cache,
                force=force,
            )
            clauses_part = self._extract_stage(
                document=document,
                stage="semantic_clauses",
                schema=ClausesExtraction,
                prompt=clauses_prompt(
                    render_chunks_for_prompt(selected_clauses),
                    self.registry,
                    long_document=True,
                    required_candidates=clause_candidates,
                ),
                use_cache=use_cache,
                force=force,
            )
            semantic = SemanticExtraction(
                definitions=definitions_part.definitions,
                clauses=clauses_part.clauses,
                warnings=[*definitions_part.warnings, *clauses_part.warnings],
            )
        else:
            semantic = self._extract_stage(
                document=document,
                stage="semantic",
                schema=SemanticExtraction,
                prompt=semantic_prompt(
                    render_chunks_for_prompt(selected_definitions),
                    self.registry,
                    long_document=False,
                ),
                use_cache=use_cache,
                force=force,
            )

        provider_model = getattr(self.provider, "model_summary", self.provider.model)

        policy, evidence_report = assemble_policy(
            document=document,
            core=core,
            risk=risk,
            semantic=semantic,
            registry=self.registry,
            provider_model=provider_model,
        )

        warnings: list[str] = []
        if evidence_report.invalid_claims:
            warnings.append(
                f"{evidence_report.invalid_claims} evidence claim(s) failed deterministic validation."
            )
        unknown_items = []
        unknown_items.extend(x.original_name for x in policy.coverages if not x.canonical_id)
        unknown_items.extend(x.original_name for x in policy.extensions if not x.canonical_id)
        unknown_items.extend(x.original_name for x in policy.exclusions if not x.canonical_id)
        unknown_items.extend(x.original_term for x in policy.definitions if not x.canonical_term)
        unknown_items.extend(x.original_name for x in policy.clauses if not x.canonical_id)
        if unknown_items:
            warnings.append(
                "Unnormalized item(s): " + "; ".join(sorted(set(unknown_items)))
            )

        run = StructuredExtractionRun(
            document_id=document.document_id,
            source_name=document.source_name,
            provider=self.provider.provider_name,
            model=provider_model,
            selected_chunks=(
                {
                    "core": [c.chunk_id for c in selected_core],
                    "risk_coverages_extensions": [c.chunk_id for c in selected_risk_coverages_extensions],
                    "risk_exclusions": [c.chunk_id for c in selected_risk_exclusions],
                    "semantic_definitions": [c.chunk_id for c in selected_definitions],
                    "semantic_clauses": [c.chunk_id for c in selected_clauses],
                }
                if long_document
                else {
                    "core": [c.chunk_id for c in selected_core],
                    "risk": [c.chunk_id for c in selected_risk],
                    "semantic": [c.chunk_id for c in selected_definitions],
                }
            ),
            core=core,
            risk=risk,
            semantic=semantic,
            evidence_report=evidence_report,
            policy_json=policy.model_dump(mode="json"),
            warnings=warnings,
        )

        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        return policy, run
