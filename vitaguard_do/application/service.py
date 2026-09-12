from __future__ import annotations

from pathlib import Path
from typing import Iterable

from vitaguard_do.application.demo import DEMO_ASSETS, prepare_demo_assets
from vitaguard_do.application.live import (
    LiveAnalysisBundle,
    LiveInputError,
    NativeTextUnavailableError,
    MultimodalTextUnavailableError,
    analyze_live_paths,
    clear_live_job,
    load_live_policy,
    prepare_live_uploads,
)
from vitaguard_do.application.models import DemoBundle, PolicyOverview, ProcessingStage, ReviewItem
from vitaguard_do.application.assistant import AskVitaGuardResult, ask_vitaguard, can_answer_locally
from vitaguard_do.comparison import ComparisonReport, ComparisonStatus, compare_policies, select_key_differences
from vitaguard_do.comparison.io import load_policy_record
from vitaguard_do.models.schema import ExtractionStatus, PolicyRecord


class DemoDataUnavailableError(RuntimeError):
    def __init__(self, missing: list[str], searched: dict[str, list[str]]):
        self.missing = missing
        self.searched = searched
        details = []
        for key in missing:
            paths = "\n".join(f"  - {p}" for p in searched.get(key, [])) or "  - nenhum caminho candidato"
            details.append(f"{key}:\n{paths}")
        super().__init__(
            "Dados de demonstracao incompletos no pacote atual. O pacote atual é autossuficiente; "
            "reextraia o ZIP original se algum artefato estiver ausente ou corrompido. "
            "Arquivos ausentes:\n" + "\n".join(details)
        )


class VitaGuardApplicationService:
    """Facade de aplicação para a UI e futuras integrações."""

    DEMO_ORDER = ("allianz", "aig", "executive_plus")

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._bundle: DemoBundle | None = None
        self._policies: dict[str, PolicyRecord] = {}
        self._live_policies: dict[str, PolicyRecord] = {}

    def prepare_demo(self) -> DemoBundle:
        files, migrated_from, searched = prepare_demo_assets(self.root)
        missing = [spec.key for spec in DEMO_ASSETS if spec.key not in files]
        if missing:
            raise DemoDataUnavailableError(missing, searched)

        self._bundle = DemoBundle(
            root=str(self.root),
            files={key: str(files[key]) for key in self.DEMO_ORDER},
            migrated_from={key: migrated_from.get(key) for key in self.DEMO_ORDER},
        )
        self._policies = {key: load_policy_record(files[key]) for key in self.DEMO_ORDER}
        return self._bundle

    def _ensure_demo(self) -> None:
        if self._bundle is None or not self._policies:
            self.prepare_demo()

    @staticmethod
    def _field_value(field, fallback: str = "Não identificado") -> str:
        if field.status == ExtractionStatus.FOUND and field.value is not None:
            return str(field.value)
        return fallback

    @classmethod
    def policy_overview(cls, policy: PolicyRecord) -> PolicyOverview:
        doc = policy.source_documents[0]
        return PolicyOverview(
            policy_id=policy.policy_id,
            insurer=cls._field_value(policy.identification.insurer),
            product=cls._field_value(policy.identification.product_name),
            source_file=doc.source_file,
            document_origin=doc.origin.value,
            document_type=doc.document_type.value,
            coverage_count=len(policy.coverages),
            extension_count=len(policy.extensions),
            exclusion_count=len(policy.exclusions),
            definition_count=len(policy.definitions),
            clause_count=len(policy.clauses),
            warning_count=len(policy.extraction.warnings),
            error_count=len(policy.extraction.errors),
        )

    def list_demo_policies(self) -> list[PolicyOverview]:
        self._ensure_demo()
        return [self.policy_overview(self._policies[key]) for key in self.DEMO_ORDER]

    def policy_ids(self) -> list[str]:
        return [p.policy_id for p in self.list_demo_policies()]

    def compare_demo(self, policy_ids: Iterable[str] | None = None) -> ComparisonReport:
        self._ensure_demo()
        ordered = [self._policies[key] for key in self.DEMO_ORDER]
        return self._compare_policy_list(ordered, policy_ids)

    @staticmethod
    def _compare_policy_list(
        policies: list[PolicyRecord],
        policy_ids: Iterable[str] | None = None,
    ) -> ComparisonReport:
        ordered = list(policies)
        if policy_ids is not None:
            requested = list(policy_ids)
            wanted = set(requested)
            ordered = [policy for policy in ordered if policy.policy_id in wanted]
            found_ids = {p.policy_id for p in ordered}
            unknown = [x for x in requested if x not in found_ids]
            if unknown:
                raise KeyError(f"Policy IDs desconhecidos: {unknown}")
        if len(ordered) < 2:
            raise ValueError("A comparacao requer pelo menos duas apolices.")
        return compare_policies(ordered)

    # -------------------------- fluxo vivo v0.8.1.1 --------------------------
    def prepare_live_uploads(self, files: list[tuple[str, bytes]]) -> tuple[str, Path, list[Path]]:
        return prepare_live_uploads(self.root, files)

    def analyze_live(
        self,
        *,
        job_id: str,
        job_dir: str | Path,
        paths: list[str | Path],
        api_key: str | None,
        progress=None,
        force: bool = False,
        provider_factory=None,
        pipeline_factory=None,
    ) -> LiveAnalysisBundle:
        kwargs = {}
        if provider_factory is not None:
            kwargs["provider_factory"] = provider_factory
        if pipeline_factory is not None:
            kwargs["pipeline_factory"] = pipeline_factory
        bundle = analyze_live_paths(
            root=self.root,
            job_id=job_id,
            job_dir=job_dir,
            paths=paths,
            api_key=api_key,
            progress=progress,
            force=force,
            **kwargs,
        )
        self._load_live_bundle(bundle)
        return bundle

    def _load_live_bundle(self, bundle: LiveAnalysisBundle) -> list[PolicyRecord]:
        ordered: list[PolicyRecord] = []
        for artifact in bundle.documents:
            policy = load_live_policy(artifact)
            ordered.append(policy)
        self._live_policies = {policy.policy_id: policy for policy in ordered}
        return ordered

    def list_live_policies(self, bundle: LiveAnalysisBundle) -> list[PolicyOverview]:
        ordered = self._load_live_bundle(bundle)
        return [self.policy_overview(policy) for policy in ordered]

    def compare_live(
        self,
        bundle: LiveAnalysisBundle,
        policy_ids: Iterable[str] | None = None,
    ) -> ComparisonReport:
        ordered = self._load_live_bundle(bundle)
        return self._compare_policy_list(ordered, policy_ids)

    @staticmethod
    def clear_live(bundle: LiveAnalysisBundle) -> None:
        clear_live_job(bundle)

    def processing_stages(self, policy_id: str) -> list[ProcessingStage]:
        self._ensure_demo()
        policy = next((p for p in self._policies.values() if p.policy_id == policy_id), None)
        if policy is None:
            policy = self._live_policies.get(policy_id)
        if policy is None:
            raise KeyError(policy_id)
        invalid = bool(policy.extraction.errors)
        return [
            ProcessingStage(id="received", label="Documento recebido", completed=True),
            ProcessingStage(id="text", label="Texto extraído", completed=True, detail=policy.extraction.extraction_method.value),
            ProcessingStage(id="structured", label="Dados estruturados", completed=True),
            ProcessingStage(id="evidence", label="Evidências disponíveis", completed=not invalid),
            ProcessingStage(id="ready", label="Pronto para comparação", completed=not invalid),
        ]

    def processing_stages_live(self, policy_id: str) -> list[ProcessingStage]:
        policy = self._live_policies.get(policy_id)
        if policy is None:
            raise KeyError(policy_id)
        invalid = bool(policy.extraction.errors)
        return [
            ProcessingStage(id="received", label="Documento recebido", completed=True),
            ProcessingStage(id="text", label="Texto extraído", completed=True, detail=policy.extraction.extraction_method.value),
            ProcessingStage(id="structured", label="Dados estruturados", completed=True),
            ProcessingStage(id="evidence", label="Evidências disponíveis", completed=not invalid),
            ProcessingStage(id="ready", label="Pronto para comparação", completed=not invalid),
        ]

    @staticmethod
    def review_items(report: ComparisonReport) -> list[ReviewItem]:
        return [
            ReviewItem(
                section=row.section,
                field_id=row.field_id,
                label=row.label,
                presence_fraction=row.presence_fraction,
                notes=list(row.notes),
            )
            for row in report.rows
            if row.status == ComparisonStatus.NEEDS_REVIEW
        ]

    @staticmethod
    def key_differences(report: ComparisonReport, *, limit: int = 12):
        return select_key_differences(report, limit=limit)

    @staticmethod
    def can_answer_locally(report: ComparisonReport, question: str) -> bool:
        return can_answer_locally(report, question)

    @staticmethod
    def ask(
        report: ComparisonReport,
        question: str,
        *,
        api_key: str | None = None,
        provider_factory=None,
    ) -> AskVitaGuardResult:
        kwargs = {}
        if provider_factory is not None:
            kwargs["provider_factory"] = provider_factory
        return ask_vitaguard(report, question, api_key=api_key, **kwargs)

    @staticmethod
    def find_row(report: ComparisonReport, section: str, field_id: str):
        for row in report.rows:
            if row.section == section and row.field_id == field_id:
                return row
        raise KeyError(f"Linha não encontrada: {section}/{field_id}")


__all__ = [
    "DemoDataUnavailableError",
    "VitaGuardApplicationService",
    "LiveAnalysisBundle",
    "LiveInputError",
    "NativeTextUnavailableError",
    "MultimodalTextUnavailableError",
]
