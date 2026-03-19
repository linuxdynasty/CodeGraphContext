"""YAML infrastructure parser for K8s, ArgoCD, Crossplane, Helm, and Kustomize.

Parses .yaml/.yml files and classifies them into infrastructure
resource types based on apiVersion + kind combinations.
"""

import re
from pathlib import Path
from typing import Any

import yaml

from ...utils.debug_log import warning_logger


# --- Domain classifiers ---

_ARGOCD_API = "argoproj.io/"
_CROSSPLANE_XRD_API = "apiextensions.crossplane.io/"
_CROSSPLANE_CLAIM_PATTERN = re.compile(r"^[a-z0-9.-]+\.crossplane\.io/")
_KUSTOMIZE_API = "kustomize.config.k8s.io/"


def _is_argocd_application(api_version: str, kind: str) -> bool:
    return api_version.startswith(_ARGOCD_API) and kind == "Application"


def _is_argocd_applicationset(api_version: str, kind: str) -> bool:
    return api_version.startswith(_ARGOCD_API) and kind == "ApplicationSet"


def _is_crossplane_xrd(api_version: str, kind: str) -> bool:
    return (
        api_version.startswith(_CROSSPLANE_XRD_API)
        and kind == "CompositeResourceDefinition"
    )


def _is_crossplane_composition(api_version: str, kind: str) -> bool:
    return api_version.startswith(_CROSSPLANE_XRD_API) and kind == "Composition"


def _is_crossplane_claim(api_version: str, kind: str) -> bool:
    """Crossplane claims have custom apiVersions like group.crossplane.io/v*.

    Exclude the well-known Crossplane system API groups.
    """
    if api_version.startswith(_CROSSPLANE_XRD_API):
        return False
    if api_version.startswith("pkg.crossplane.io/"):
        return False
    return bool(_CROSSPLANE_CLAIM_PATTERN.match(api_version))


def _is_kustomization(api_version: str | None, kind: str | None, filename: str) -> bool:
    if api_version and api_version.startswith(_KUSTOMIZE_API):
        return True
    if kind == "Kustomization" and (api_version or "").startswith("kustomize"):
        return True
    return filename.lower() in (
        "kustomization.yaml",
        "kustomization.yml",
    )


def _is_helm_chart(filename: str) -> bool:
    return filename.lower() in ("chart.yaml", "chart.yml")


def _is_helm_values(filename: str) -> bool:
    lower = filename.lower()
    return lower.startswith("values") and lower.endswith((".yaml", ".yml"))


def _has_k8s_api_version(api_version: str | None) -> bool:
    """Return True if the doc has a non-empty apiVersion field.

    This is a broad check — any YAML document with an apiVersion
    is treated as a K8s-style resource. More specific classifiers
    (ArgoCD, Crossplane, etc.) run first and take priority.
    """
    if not api_version:
        return False
    return True


class InfraYAMLParser:
    """Parser for infrastructure YAML files.

    Does not use tree-sitter. Parses via PyYAML and classifies
    documents by their apiVersion/kind into graph node types.

    Args:
        language_name: Language identifier (always 'yaml').
    """

    def __init__(self, language_name: str) -> None:
        self.language_name = language_name

    def parse(
        self,
        path: str,
        is_dependency: bool = False,
        index_source: bool = True,
    ) -> dict[str, Any]:
        """Parse a YAML file and return classified infrastructure items.

        Args:
            path: Absolute path to the YAML file.
            is_dependency: Whether this file is a dependency.
            index_source: Whether to store raw source.

        Returns:
            Dict with keys for each resource type found, plus
            standard keys (path, lang, is_dependency).
        """
        result: dict[str, Any] = {
            "path": path,
            "lang": "yaml",
            "is_dependency": is_dependency,
            "functions": [],
            "classes": [],
            "imports": [],
            "function_calls": [],
            "variables": [],
            # Infrastructure categories
            "k8s_resources": [],
            "argocd_applications": [],
            "argocd_applicationsets": [],
            "crossplane_xrds": [],
            "crossplane_compositions": [],
            "crossplane_claims": [],
            "kustomize_overlays": [],
            "helm_charts": [],
            "helm_values": [],
        }

        file_path = Path(path)
        filename = file_path.name

        # Handle Helm Chart.yaml and values*.yaml by filename
        if _is_helm_chart(filename):
            self._parse_helm_chart(file_path, result)
            return result

        if _is_helm_values(filename):
            self._parse_helm_values(file_path, result)
            return result

        # Parse general YAML documents
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            warning_logger(f"Cannot read {path}: {e}")
            return result

        docs = self._safe_load_all(content)
        if not docs:
            return result

        # Track line offsets for multi-document YAML
        line_offsets = self._compute_doc_line_offsets(content)

        for doc_idx, doc in enumerate(docs):
            if not isinstance(doc, dict):
                continue

            line_number = line_offsets[doc_idx] if doc_idx < len(line_offsets) else 1

            api_version = doc.get("apiVersion", "")
            kind = doc.get("kind", "")
            metadata = doc.get("metadata", {}) or {}

            # Kustomization detection (can also be by filename)
            if _is_kustomization(api_version, kind, filename):
                self._parse_kustomization(doc, path, line_number, result)
                continue

            if not api_version or not kind:
                continue

            if _is_argocd_application(api_version, kind):
                self._parse_argocd_app(doc, metadata, path, line_number, result)
            elif _is_argocd_applicationset(api_version, kind):
                self._parse_argocd_appset(doc, metadata, path, line_number, result)
            elif _is_crossplane_xrd(api_version, kind):
                self._parse_crossplane_xrd(doc, metadata, path, line_number, result)
            elif _is_crossplane_composition(api_version, kind):
                self._parse_crossplane_composition(
                    doc, metadata, path, line_number, result
                )
            elif _is_crossplane_claim(api_version, kind):
                self._parse_crossplane_claim(
                    doc,
                    metadata,
                    api_version,
                    kind,
                    path,
                    line_number,
                    result,
                )
            elif _has_k8s_api_version(api_version):
                self._parse_k8s_resource(
                    doc,
                    metadata,
                    api_version,
                    kind,
                    path,
                    line_number,
                    result,
                )

        return result

    # --- Multi-doc helpers ---

    def _safe_load_all(self, content: str) -> list[dict[str, Any]]:
        """Load all YAML documents, returning list of dicts."""
        try:
            return list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            warning_logger(f"YAML parse error: {e}")
            return []

    def _compute_doc_line_offsets(self, content: str) -> list[int]:
        """Compute 1-based line numbers for each `---` separator.

        The first document starts at line 1.
        """
        offsets = [1]
        for i, line in enumerate(content.splitlines(), start=1):
            if line.strip() == "---":
                offsets.append(i + 1)
        return offsets

    # --- ArgoCD ---

    def _parse_argocd_app(
        self,
        doc: dict,
        metadata: dict,
        path: str,
        line_number: int,
        result: dict,
    ) -> None:
        spec = doc.get("spec", {}) or {}
        source = spec.get("source", {}) or {}
        dest = spec.get("destination", {}) or {}

        result["argocd_applications"].append(
            {
                "name": metadata.get("name", ""),
                "line_number": line_number,
                "namespace": metadata.get("namespace", ""),
                "project": spec.get("project", ""),
                "source_repo": source.get("repoURL", ""),
                "source_path": source.get("path", ""),
                "source_revision": source.get("targetRevision", ""),
                "dest_server": dest.get("server", ""),
                "dest_namespace": dest.get("namespace", ""),
                "path": path,
                "lang": "yaml",
            }
        )

    def _parse_argocd_appset(
        self,
        doc: dict,
        metadata: dict,
        path: str,
        line_number: int,
        result: dict,
    ) -> None:
        spec = doc.get("spec", {}) or {}
        generators_raw = spec.get("generators", []) or []
        generator_types = []
        for gen in generators_raw:
            if isinstance(gen, dict):
                generator_types.extend(gen.keys())

        result["argocd_applicationsets"].append(
            {
                "name": metadata.get("name", ""),
                "line_number": line_number,
                "namespace": metadata.get("namespace", ""),
                "generators": ",".join(generator_types),
                "path": path,
                "lang": "yaml",
            }
        )

    # --- Crossplane ---

    def _parse_crossplane_xrd(
        self,
        doc: dict,
        metadata: dict,
        path: str,
        line_number: int,
        result: dict,
    ) -> None:
        spec = doc.get("spec", {}) or {}
        names = spec.get("names", {}) or {}
        claim_names = spec.get("claimNames", {}) or {}

        result["crossplane_xrds"].append(
            {
                "name": metadata.get("name", ""),
                "line_number": line_number,
                "group": spec.get("group", ""),
                "kind": names.get("kind", ""),
                "plural": names.get("plural", ""),
                "claim_kind": claim_names.get("kind", ""),
                "claim_plural": claim_names.get("plural", ""),
                "path": path,
                "lang": "yaml",
            }
        )

    def _parse_crossplane_composition(
        self,
        doc: dict,
        metadata: dict,
        path: str,
        line_number: int,
        result: dict,
    ) -> None:
        spec = doc.get("spec", {}) or {}
        composite_ref = spec.get("compositeTypeRef", {}) or {}
        resources_raw = spec.get("resources", []) or []

        resource_names = []
        for res in resources_raw:
            if isinstance(res, dict) and "name" in res:
                resource_names.append(res["name"])

        result["crossplane_compositions"].append(
            {
                "name": metadata.get("name", ""),
                "line_number": line_number,
                "composite_api_version": composite_ref.get("apiVersion", ""),
                "composite_kind": composite_ref.get("kind", ""),
                "resource_count": len(resources_raw),
                "resource_names": ",".join(resource_names),
                "path": path,
                "lang": "yaml",
            }
        )

    def _parse_crossplane_claim(
        self,
        doc: dict,
        metadata: dict,
        api_version: str,
        kind: str,
        path: str,
        line_number: int,
        result: dict,
    ) -> None:
        result["crossplane_claims"].append(
            {
                "name": metadata.get("name", ""),
                "line_number": line_number,
                "kind": kind,
                "api_version": api_version,
                "namespace": metadata.get("namespace", ""),
                "path": path,
                "lang": "yaml",
            }
        )

    # --- K8s ---

    def _parse_k8s_resource(
        self,
        doc: dict,
        metadata: dict,
        api_version: str,
        kind: str,
        path: str,
        line_number: int,
        result: dict,
    ) -> None:
        annotations = metadata.get("annotations", {}) or {}
        labels = metadata.get("labels", {}) or {}

        node: dict[str, Any] = {
            "name": metadata.get("name", ""),
            "line_number": line_number,
            "kind": kind,
            "api_version": api_version,
            "namespace": metadata.get("namespace", ""),
            "path": path,
            "lang": "yaml",
        }

        if annotations:
            node["annotations"] = str(annotations)
        if labels:
            node["labels"] = str(labels)

        # Extract container images from workload resources
        if kind in ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"):
            images = self._extract_container_images(doc)
            if images:
                node["container_images"] = ",".join(images)

        result["k8s_resources"].append(node)

    def _extract_container_images(self, doc: dict) -> list[str]:
        """Extract container image references from a workload spec.

        Handles Deployment/StatefulSet/DaemonSet/Job/CronJob pod
        template specs, extracting image names from both containers
        and initContainers.

        Args:
            doc: Parsed YAML document dict.

        Returns:
            List of image strings (e.g. ['myorg/my-api:latest']).
        """
        images: list[str] = []
        spec = doc.get("spec", {}) or {}

        # Job wraps in spec.template, CronJob wraps in spec.jobTemplate.spec.template
        template = spec.get("template", {}) or {}
        if not template and spec.get("jobTemplate"):
            job_spec = (spec.get("jobTemplate", {}) or {}).get("spec", {}) or {}
            template = job_spec.get("template", {}) or {}

        pod_spec = (template.get("spec", {}) or {})
        for container in pod_spec.get("containers", []) or []:
            if isinstance(container, dict) and container.get("image"):
                images.append(container["image"])
        for container in pod_spec.get("initContainers", []) or []:
            if isinstance(container, dict) and container.get("image"):
                images.append(container["image"])
        return images

    # --- Kustomize ---

    def _parse_kustomization(
        self,
        doc: dict,
        path: str,
        line_number: int,
        result: dict,
    ) -> None:
        resources = doc.get("resources", []) or []
        patches = doc.get("patches", []) or []
        patch_paths = []
        for p in patches:
            if isinstance(p, dict) and "path" in p:
                patch_paths.append(p["path"])

        result["kustomize_overlays"].append(
            {
                "name": "kustomization",
                "line_number": line_number,
                "namespace": doc.get("namespace", ""),
                "resources": resources,
                "patches": patch_paths,
                "path": path,
                "lang": "yaml",
            }
        )

    # --- Helm ---

    def _parse_helm_chart(self, file_path: Path, result: dict) -> None:
        try:
            content = file_path.read_text(encoding="utf-8")
            doc = yaml.safe_load(content)
        except (OSError, yaml.YAMLError) as e:
            warning_logger(f"Cannot parse Chart.yaml: {e}")
            return

        if not isinstance(doc, dict):
            return

        deps = doc.get("dependencies", []) or []
        dep_names = [d.get("name", "") for d in deps if isinstance(d, dict)]

        result["helm_charts"].append(
            {
                "name": doc.get("name", ""),
                "line_number": 1,
                "version": doc.get("version", ""),
                "app_version": str(doc.get("appVersion", "")),
                "chart_type": doc.get("type", "application"),
                "description": doc.get("description", ""),
                "dependencies": ",".join(dep_names),
                "path": str(file_path),
                "lang": "yaml",
            }
        )

    def _parse_helm_values(self, file_path: Path, result: dict) -> None:
        try:
            content = file_path.read_text(encoding="utf-8")
            doc = yaml.safe_load(content)
        except (OSError, yaml.YAMLError) as e:
            warning_logger(f"Cannot parse values YAML: {e}")
            return

        if not isinstance(doc, dict):
            return

        result["helm_values"].append(
            {
                "name": file_path.stem,
                "line_number": 1,
                "top_level_keys": ",".join(str(k) for k in doc.keys()),
                "path": str(file_path),
                "lang": "yaml",
            }
        )
