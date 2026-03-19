"""Ecosystem query handlers for MCP tools.

Provides high-level ecosystem queries that return structured
data from the graph: overview, deployment traces, blast radius,
resource search, and relationship analysis.
"""

from typing import Any

from ...core.database import DatabaseManager


def get_ecosystem_overview(
    db_manager: DatabaseManager,
) -> dict[str, Any]:
    """Get a high-level overview of the indexed ecosystem.

    Returns repos, tiers, stats, and cross-repo link counts.
    """
    driver = db_manager.get_driver()

    with driver.session() as session:
        # Ecosystem info
        eco_result = session.run("""
            OPTIONAL MATCH (e:Ecosystem)
            RETURN e.name as name, e.org as org
            LIMIT 1
        """).single()

        # Tier summary
        tiers = session.run("""
            MATCH (t:Tier)
            OPTIONAL MATCH (t)-[:CONTAINS]->(r:Repository)
            RETURN t.name as tier,
                   t.risk_level as risk,
                   collect(r.name) as repos
            ORDER BY CASE t.risk_level
                         WHEN 'critical' THEN 4
                         WHEN 'high' THEN 3
                         WHEN 'medium' THEN 2
                         WHEN 'low' THEN 1
                         ELSE 0
                     END DESC
        """).data()

        # Repo stats
        repo_stats = session.run("""
            MATCH (r:Repository)
            OPTIONAL MATCH (r)-[:CONTAINS*]->(f:File)
            OPTIONAL MATCH (r)-[:DEPENDS_ON]->(dep:Repository)
            RETURN r.name as name,
                   r.path as path,
                   count(DISTINCT f) as files,
                   collect(DISTINCT dep.name) as depends_on
            ORDER BY r.name
        """).data()

        # Infrastructure node counts
        infra_counts = session.run("""
            OPTIONAL MATCH (k:K8sResource) WITH count(k) as k8s
            OPTIONAL MATCH (a:ArgoCDApplication) WITH k8s, count(a) as argocd
            OPTIONAL MATCH (x:CrossplaneXRD) WITH k8s, argocd, count(x) as xrds
            OPTIONAL MATCH (t:TerraformResource) WITH k8s, argocd, xrds, count(t) as terraform
            OPTIONAL MATCH (h:HelmChart) WITH k8s, argocd, xrds, terraform, count(h) as helm
            RETURN k8s, argocd, xrds, terraform, helm
        """).single()

        # Cross-repo relationship counts
        rel_counts = session.run("""
            OPTIONAL MATCH ()-[s:SOURCES_FROM]->() WITH count(s) as sources_from
            OPTIONAL MATCH ()-[d:DEPLOYS]->() WITH sources_from, count(d) as deploys
            OPTIONAL MATCH ()-[sat:SATISFIED_BY]->() WITH sources_from, deploys, count(sat) as satisfied_by
            OPTIONAL MATCH ()-[dep:DEPENDS_ON]->() WITH sources_from, deploys, satisfied_by, count(dep) as depends_on
            RETURN sources_from, deploys, satisfied_by, depends_on
        """).single()

    eco_name = eco_result["name"] if eco_result else None
    eco_org = eco_result["org"] if eco_result else None

    result: dict[str, Any] = {
        "tiers": tiers,
        "repos": repo_stats,
        "infrastructure_counts": dict(infra_counts) if infra_counts else {},
        "cross_repo_relationships": dict(rel_counts) if rel_counts else {},
    }

    if eco_name:
        result["ecosystem"] = {"name": eco_name, "org": eco_org}
    else:
        result["mode"] = "standalone"
        result["note"] = (
            "No ecosystem manifest. Showing all indexed repositories."
        )

    return result


def trace_deployment_chain(
    db_manager: DatabaseManager,
    service_name: str,
) -> dict[str, Any]:
    """Trace the full deployment chain for a service.

    Follows: Repository -> ArgoCD Application ->
    K8s Resources -> Crossplane Claims -> XRDs ->
    Compositions, plus Terraform resources.

    Args:
        db_manager: Database manager.
        service_name: Name of the repo/service to trace.

    Returns:
        Structured chain from source to infrastructure.
    """
    driver = db_manager.get_driver()

    with driver.session() as session:
        # Find the repo
        repo = session.run(
            "MATCH (r:Repository) "
            "WHERE r.name CONTAINS $name "
            "RETURN r.name as name, r.path as path "
            "LIMIT 1",
            name=service_name,
        ).single()

        if not repo:
            return {"error": f"Repository '{service_name}' not found"}

        # ArgoCD applications sourcing from this repo
        argocd_apps = session.run(
            """
            MATCH (app:ArgoCDApplication)-[:SOURCES_FROM]->(r:Repository)
            WHERE r.name CONTAINS $name
            RETURN app.name as app_name,
                   app.project as project,
                   app.dest_namespace as namespace,
                   app.source_path as source_path
        """,
            name=service_name,
        ).data()

        # K8s resources in the repo
        k8s_resources = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)-[:CONTAINS]->(k:K8sResource)
            WHERE r.name CONTAINS $name
            RETURN k.name as name, k.kind as kind,
                   k.namespace as namespace,
                   f.relative_path as file
        """,
            name=service_name,
        ).data()

        # Crossplane claims in the repo
        claims = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)-[:CONTAINS]->(claim:CrossplaneClaim)
            WHERE r.name CONTAINS $name
            OPTIONAL MATCH (claim)-[:SATISFIED_BY]->(xrd:CrossplaneXRD)
            OPTIONAL MATCH (xrd)-[:IMPLEMENTED_BY]->(comp:CrossplaneComposition)
            RETURN claim.name as claim_name,
                   claim.kind as claim_kind,
                   xrd.kind as xrd_kind,
                   xrd.group as xrd_group,
                   comp.name as composition_name
        """,
            name=service_name,
        ).data()

        # Terraform resources in the repo
        terraform = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)-[:CONTAINS]->(tf:TerraformResource)
            WHERE r.name CONTAINS $name
            RETURN tf.name as name,
                   tf.resource_type as resource_type,
                   f.relative_path as file
        """,
            name=service_name,
        ).data()

        # Terraform modules used
        tf_modules = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)-[:CONTAINS]->(mod:TerraformModule)
            WHERE r.name CONTAINS $name
            RETURN mod.name as name,
                   mod.source as source,
                   mod.version as version
        """,
            name=service_name,
        ).data()

    return {
        "repository": dict(repo),
        "argocd_applications": argocd_apps,
        "k8s_resources": k8s_resources,
        "crossplane_claims": claims,
        "terraform_resources": terraform,
        "terraform_modules": tf_modules,
    }


def find_blast_radius(
    db_manager: DatabaseManager,
    target: str,
    target_type: str = "repository",
) -> dict[str, Any]:
    """Find all repos/resources affected by changing a target.

    Uses graph traversal to find transitive dependents.

    Args:
        db_manager: Database manager.
        target: Name of the target (repo, module, XRD).
        target_type: One of 'repository', 'terraform_module',
            'crossplane_xrd'.

    Returns:
        Affected repos with hop counts and tier info.
    """
    driver = db_manager.get_driver()

    with driver.session() as session:
        if target_type == "repository":
            affected = session.run(
                """
                MATCH (source:Repository)
                WHERE source.name CONTAINS $target_name
                OPTIONAL MATCH path = (source)<-[:DEPENDS_ON*1..5]-(affected:Repository)
                OPTIONAL MATCH (affected)<-[:CONTAINS]-(tier:Tier)
                RETURN DISTINCT
                    affected.name as repo,
                    tier.name as tier,
                    tier.risk_level as risk,
                    length(path) as hops
                ORDER BY hops
            """,
                target_name=target,
            ).data()

        elif target_type == "terraform_module":
            affected = session.run(
                """
                MATCH (mod:TerraformModule)
                WHERE mod.name CONTAINS $target_name
                   OR mod.source CONTAINS $target_name
                MATCH (f:File)-[:CONTAINS]->(mod)
                MATCH (repo:Repository)-[:CONTAINS*]->(f)
                OPTIONAL MATCH (repo)<-[:DEPENDS_ON*0..5]-(affected:Repository)
                OPTIONAL MATCH (affected)<-[:CONTAINS]-(tier:Tier)
                RETURN DISTINCT
                    affected.name as repo,
                    tier.name as tier,
                    tier.risk_level as risk
            """,
                target_name=target,
            ).data()

        elif target_type == "crossplane_xrd":
            affected = session.run(
                """
                MATCH (xrd:CrossplaneXRD)
                WHERE xrd.kind CONTAINS $target_name
                   OR xrd.name CONTAINS $target_name
                OPTIONAL MATCH (claim:CrossplaneClaim)-[:SATISFIED_BY]->(xrd)
                MATCH (f:File)-[:CONTAINS]->(claim)
                MATCH (repo:Repository)-[:CONTAINS*]->(f)
                OPTIONAL MATCH (affected)<-[:CONTAINS]-(tier:Tier)
                RETURN DISTINCT
                    repo.name as repo,
                    tier.name as tier,
                    claim.name as claim
            """,
                target_name=target,
            ).data()
        else:
            return {"error": f"Unknown target_type: {target_type}"}

    result: dict[str, Any] = {
        "target": target,
        "target_type": target_type,
        "affected": affected,
        "affected_count": len(affected),
    }
    has_null_tier = any(
        a.get("tier") is None or a.get("risk") is None
        for a in affected
        if a.get("repo") is not None
    )
    if has_null_tier:
        result["note"] = (
            "Tier and risk levels require an ecosystem manifest."
        )
    return result


def find_infra_resources(
    db_manager: DatabaseManager,
    query: str,
    category: str = "",
) -> dict[str, Any]:
    """Search infrastructure resources by name/type.

    Args:
        db_manager: Database manager.
        query: Search query string.
        category: Optional filter: k8s, terraform, argocd,
            crossplane, helm.

    Returns:
        Matching resources grouped by type.
    """
    driver = db_manager.get_driver()
    results: dict[str, list] = {}

    with driver.session() as session:
        if not category or category == "k8s":
            results["k8s_resources"] = session.run(
                """
                MATCH (k:K8sResource)
                WHERE k.name CONTAINS $search
                   OR k.kind CONTAINS $search
                MATCH (f:File)-[:CONTAINS]->(k)
                RETURN k.name as name, k.kind as kind,
                       k.namespace as namespace,
                       f.relative_path as file
                LIMIT 50
            """,
                search=query,
            ).data()

        if not category or category == "terraform":
            results["terraform_resources"] = session.run(
                """
                MATCH (t:TerraformResource)
                WHERE t.name CONTAINS $search
                   OR t.resource_type CONTAINS $search
                MATCH (f:File)-[:CONTAINS]->(t)
                RETURN t.name as name,
                       t.resource_type as type,
                       f.relative_path as file
                LIMIT 50
            """,
                search=query,
            ).data()

        if not category or category == "argocd":
            results["argocd_applications"] = session.run(
                """
                MATCH (a:ArgoCDApplication)
                WHERE a.name CONTAINS $search
                RETURN a.name as name,
                       a.project as project,
                       a.dest_namespace as namespace,
                       a.source_repo as source_repo
                LIMIT 50
            """,
                search=query,
            ).data()

        if not category or category == "crossplane":
            xrds = session.run(
                """
                MATCH (x:CrossplaneXRD)
                WHERE x.name CONTAINS $search
                   OR x.kind CONTAINS $search
                RETURN x.name as name, x.kind as kind,
                       x.group as api_group,
                       x.claim_kind as claim_kind
                LIMIT 50
            """,
                search=query,
            ).data()

            claims = session.run(
                """
                MATCH (c:CrossplaneClaim)
                WHERE c.name CONTAINS $search
                   OR c.kind CONTAINS $search
                RETURN c.name as name, c.kind as kind,
                       c.namespace as namespace
                LIMIT 50
            """,
                search=query,
            ).data()

            results["crossplane_xrds"] = xrds
            results["crossplane_claims"] = claims

        if not category or category == "helm":
            results["helm_charts"] = session.run(
                """
                MATCH (h:HelmChart)
                WHERE h.name CONTAINS $search
                RETURN h.name as name,
                       h.version as version,
                       h.app_version as app_version
                LIMIT 50
            """,
                search=query,
            ).data()

    return {"query": query, "category": category, "results": results}


def analyze_infra_relationships(
    db_manager: DatabaseManager,
    query_type: str,
    target: str,
) -> dict[str, Any]:
    """Analyze infrastructure relationships.

    Args:
        db_manager: Database manager.
        query_type: Type of analysis. One of:
            'what_deploys' - What ArgoCD apps deploy this
            'what_provisions' - What Crossplane/TF provisions this
            'who_consumes_xrd' - What repos use this XRD
            'module_consumers' - What uses this TF module
        target: Name of the target resource.

    Returns:
        Relationship analysis results.
    """
    driver = db_manager.get_driver()

    with driver.session() as session:
        if query_type == "what_deploys":
            data = session.run(
                """
                MATCH (app:ArgoCDApplication)-[:DEPLOYS]->(k:K8sResource)
                WHERE k.name CONTAINS $target_name
                   OR app.name CONTAINS $target_name
                RETURN app.name as app_name,
                       k.name as resource_name,
                       k.kind as resource_kind,
                       k.namespace as namespace
            """,
                target_name=target,
            ).data()

        elif query_type == "what_provisions":
            data = session.run(
                """
                MATCH (claim:CrossplaneClaim)-[:SATISFIED_BY]->(xrd:CrossplaneXRD)
                WHERE claim.name CONTAINS $target_name
                OPTIONAL MATCH (xrd)-[:IMPLEMENTED_BY]->(comp:CrossplaneComposition)
                RETURN claim.name as claim,
                       xrd.kind as xrd_kind,
                       comp.name as composition
            """,
                target_name=target,
            ).data()

        elif query_type == "who_consumes_xrd":
            data = session.run(
                """
                MATCH (xrd:CrossplaneXRD)
                WHERE xrd.kind CONTAINS $target_name
                   OR xrd.name CONTAINS $target_name
                MATCH (claim:CrossplaneClaim)-[:SATISFIED_BY]->(xrd)
                MATCH (f:File)-[:CONTAINS]->(claim)
                MATCH (repo:Repository)-[:CONTAINS*]->(f)
                RETURN DISTINCT
                    repo.name as repo,
                    claim.name as claim,
                    f.relative_path as file
            """,
                target_name=target,
            ).data()

        elif query_type == "module_consumers":
            data = session.run(
                """
                MATCH (mod:TerraformModule)
                WHERE mod.name CONTAINS $target_name
                   OR mod.source CONTAINS $target_name
                MATCH (f:File)-[:CONTAINS]->(mod)
                MATCH (repo:Repository)-[:CONTAINS*]->(f)
                RETURN DISTINCT
                    repo.name as repo,
                    mod.name as module_name,
                    mod.source as source,
                    f.relative_path as file
            """,
                target_name=target,
            ).data()

        else:
            return {"error": f"Unknown query_type: {query_type}"}

    return {
        "query_type": query_type,
        "target": target,
        "results": data,
        "count": len(data),
    }


def get_repo_summary(
    db_manager: DatabaseManager,
    repo_name: str,
) -> dict[str, Any]:
    """Get a structured summary of a repository.

    Args:
        db_manager: Database manager.
        repo_name: Name of the repository.

    Returns:
        Summary with files, code entities, infra resources,
        and ecosystem connections.
    """
    driver = db_manager.get_driver()

    with driver.session() as session:
        # Basic info
        repo = session.run(
            "MATCH (r:Repository) "
            "WHERE r.name CONTAINS $name "
            "RETURN r.name as name, r.path as path "
            "LIMIT 1",
            name=repo_name,
        ).single()

        if not repo:
            return {"error": f"Repository '{repo_name}' not found"}

        # File count by extension
        file_stats = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
            WHERE r.name CONTAINS $name
            RETURN f.name as file,
                   split(f.name, '.')[-1] as ext
        """,
            name=repo_name,
        ).data()

        ext_counts: dict[str, int] = {}
        for f in file_stats:
            ext = f.get("ext", "")
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        # Code entities
        code_stats = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
            WHERE r.name CONTAINS $name
            OPTIONAL MATCH (f)-[:CONTAINS]->(fn:Function)
            OPTIONAL MATCH (f)-[:CONTAINS]->(cls:Class)
            RETURN count(DISTINCT fn) as functions,
                   count(DISTINCT cls) as classes
        """,
            name=repo_name,
        ).single()

        # Infrastructure resources
        infra = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)-[:CONTAINS]->(n)
            WHERE r.name CONTAINS $name
              AND (n:K8sResource OR n:ArgoCDApplication
                   OR n:CrossplaneXRD OR n:CrossplaneClaim
                   OR n:TerraformResource OR n:HelmChart)
            RETURN labels(n)[0] as type,
                   count(n) as count
        """,
            name=repo_name,
        ).data()

        # Dependencies
        deps = session.run(
            """
            MATCH (r:Repository)-[:DEPENDS_ON]->(dep:Repository)
            WHERE r.name CONTAINS $name
            RETURN collect(dep.name) as dependencies
        """,
            name=repo_name,
        ).single()

        # Dependents
        dependents = session.run(
            """
            MATCH (r:Repository)<-[:DEPENDS_ON]-(dep:Repository)
            WHERE r.name CONTAINS $name
            RETURN collect(dep.name) as dependents
        """,
            name=repo_name,
        ).single()

        # Tier
        tier = session.run(
            """
            MATCH (t:Tier)-[:CONTAINS]->(r:Repository)
            WHERE r.name CONTAINS $name
            RETURN t.name as tier, t.risk_level as risk_level
            LIMIT 1
        """,
            name=repo_name,
        ).single()

    summary: dict[str, Any] = {
        "name": repo["name"],
        "path": repo["path"],
        "file_count": len(file_stats),
        "files_by_extension": ext_counts,
        "code": dict(code_stats) if code_stats else {},
        "infrastructure": infra,
        "dependencies": deps["dependencies"] if deps else [],
        "dependents": dependents["dependents"] if dependents else [],
    }
    if tier:
        summary["tier"] = dict(tier)
    return summary


def get_repo_context(
    db_manager: DatabaseManager,
    repo_name: str,
) -> dict[str, Any]:
    """Get complete context for a repository in a single call.

    Returns repository metadata, code summary, infrastructure
    resources, intra-repo relationships, and ecosystem info.
    Designed as the first call for any repo documentation task.

    Args:
        db_manager: Database manager.
        repo_name: Name of the repository.

    Returns:
        Structured context with repository, code, infrastructure,
        relationships, and ecosystem sections.
    """
    driver = db_manager.get_driver()

    with driver.session() as session:
        # Repository info
        repo = session.run(
            "MATCH (r:Repository) "
            "WHERE r.name CONTAINS $name "
            "RETURN r.name as name, r.path as path "
            "LIMIT 1",
            name=repo_name,
        ).single()

        if not repo:
            return {"error": f"Repository '{repo_name}' not found"}

        # File stats
        file_stats = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
            WHERE r.name CONTAINS $name
            RETURN f.name as file,
                   split(f.name, '.')[-1] as ext
        """,
            name=repo_name,
        ).data()

        ext_counts: dict[str, int] = {}
        for f in file_stats:
            ext = f.get("ext", "")
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

        # Code summary
        code_stats = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
            WHERE r.name CONTAINS $name
            OPTIONAL MATCH (f)-[:CONTAINS]->(fn:Function)
            OPTIONAL MATCH (f)-[:CONTAINS]->(cls:Class)
            RETURN count(DISTINCT fn) as functions,
                   count(DISTINCT cls) as classes
        """,
            name=repo_name,
        ).single()

        # Detect languages from file extensions
        lang_map = {
            "py": "python",
            "go": "go",
            "js": "javascript",
            "ts": "typescript",
            "rs": "rust",
            "rb": "ruby",
            "java": "java",
            "c": "c",
            "cpp": "cpp",
            "cs": "csharp",
            "php": "php",
            "ex": "elixir",
            "swift": "swift",
        }
        languages = sorted({
            lang_map[ext]
            for ext in ext_counts
            if ext in lang_map
        })

        # Entry points (main/handler functions)
        entry_points = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(fn:Function)
            WHERE r.name CONTAINS $name
              AND (fn.name IN ['main', 'handler', 'lambda_handler',
                               'app', 'run', 'cli', 'entrypoint']
                   OR fn.name STARTS WITH 'main')
            RETURN fn.name as name,
                   f.relative_path as file,
                   fn.line_number as line
            LIMIT 20
        """,
            name=repo_name,
        ).data()

        # K8s resources
        k8s_resources = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(k:K8sResource)
            WHERE r.name CONTAINS $name
            RETURN k.name as name, k.kind as kind,
                   k.namespace as namespace,
                   f.relative_path as file
        """,
            name=repo_name,
        ).data()

        # Terraform resources
        terraform_resources = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(t:TerraformResource)
            WHERE r.name CONTAINS $name
            RETURN t.name as name,
                   t.resource_type as resource_type,
                   f.relative_path as file
        """,
            name=repo_name,
        ).data()

        # Terraform modules
        terraform_modules = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(m:TerraformModule)
            WHERE r.name CONTAINS $name
            RETURN m.name as name,
                   m.source as source,
                   m.version as version
        """,
            name=repo_name,
        ).data()

        # Terraform variables
        terraform_variables = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(v:TerraformVariable)
            WHERE r.name CONTAINS $name
            RETURN v.name as name,
                   v.description as description,
                   v.default as default
        """,
            name=repo_name,
        ).data()

        # Terraform outputs
        terraform_outputs = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(o:TerraformOutput)
            WHERE r.name CONTAINS $name
            RETURN o.name as name,
                   o.description as description
        """,
            name=repo_name,
        ).data()

        # ArgoCD applications
        argocd_apps = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(a:ArgoCDApplication)
            WHERE r.name CONTAINS $name
            RETURN a.name as name, a.project as project,
                   a.dest_namespace as dest_namespace,
                   a.source_repo as source_repo
        """,
            name=repo_name,
        ).data()

        # ArgoCD applicationsets
        argocd_appsets = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(a:ArgoCDApplicationSet)
            WHERE r.name CONTAINS $name
            RETURN a.name as name, a.generators as generators
        """,
            name=repo_name,
        ).data()

        # Crossplane XRDs
        crossplane_xrds = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(x:CrossplaneXRD)
            WHERE r.name CONTAINS $name
            RETURN x.name as name, x.kind as kind,
                   x.claim_kind as claim_kind
        """,
            name=repo_name,
        ).data()

        # Crossplane compositions
        crossplane_compositions = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(c:CrossplaneComposition)
            WHERE r.name CONTAINS $name
            RETURN c.name as name,
                   c.composite_kind as composite_kind
        """,
            name=repo_name,
        ).data()

        # Crossplane claims
        crossplane_claims = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(c:CrossplaneClaim)
            WHERE r.name CONTAINS $name
            RETURN c.name as name, c.kind as kind,
                   c.namespace as namespace
        """,
            name=repo_name,
        ).data()

        # Helm charts
        helm_charts = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(h:HelmChart)
            WHERE r.name CONTAINS $name
            RETURN h.name as name, h.version as version,
                   h.app_version as app_version
        """,
            name=repo_name,
        ).data()

        # Helm values
        helm_values = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(h:HelmValues)
            WHERE r.name CONTAINS $name
            RETURN h.name as name,
                   h.top_level_keys as top_level_keys
        """,
            name=repo_name,
        ).data()

        # Kustomize overlays
        kustomize_overlays = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(k:KustomizeOverlay)
            WHERE r.name CONTAINS $name
            RETURN k.name as name, k.namespace as namespace,
                   k.resources as resources
        """,
            name=repo_name,
        ).data()

        # Terragrunt configs
        terragrunt_configs = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f:File)
                  -[:CONTAINS]->(t:TerragruntConfig)
            WHERE r.name CONTAINS $name
            RETURN t.name as name,
                   t.terraform_source as terraform_source
        """,
            name=repo_name,
        ).data()

        # Intra-repo relationships
        relationships = session.run(
            """
            MATCH (r:Repository)-[:CONTAINS*]->(f1:File)-[:CONTAINS]->(n1)
                  -[rel]->(n2)<-[:CONTAINS]-(f2:File)<-[:CONTAINS*]-(r)
            WHERE r.name CONTAINS $name
              AND type(rel) IN [
                'SELECTS', 'CONFIGURES', 'PATCHES', 'ROUTES_TO',
                'SATISFIED_BY', 'IMPLEMENTED_BY', 'RUNS_IMAGE',
                'USES_IAM'
            ]
            RETURN DISTINCT type(rel) as type,
                   n1.name as from_name,
                   labels(n1)[0] as from_kind,
                   n2.name as to_name,
                   labels(n2)[0] as to_kind
            LIMIT 100
        """,
            name=repo_name,
        ).data()

        # Ecosystem info (tier, dependencies, dependents)
        tier = session.run(
            """
            MATCH (t:Tier)-[:CONTAINS]->(r:Repository)
            WHERE r.name CONTAINS $name
            RETURN t.name as tier, t.risk_level as risk_level
            LIMIT 1
        """,
            name=repo_name,
        ).single()

        deps = session.run(
            """
            MATCH (r:Repository)-[:DEPENDS_ON]->(dep:Repository)
            WHERE r.name CONTAINS $name
            RETURN collect(dep.name) as dependencies
        """,
            name=repo_name,
        ).single()

        dependents = session.run(
            """
            MATCH (r:Repository)<-[:DEPENDS_ON]-(dep:Repository)
            WHERE r.name CONTAINS $name
            RETURN collect(dep.name) as dependents
        """,
            name=repo_name,
        ).single()

    # Build infrastructure section
    infrastructure: dict[str, Any] = {}
    if k8s_resources:
        infrastructure["k8s_resources"] = k8s_resources
    if terraform_resources:
        infrastructure["terraform_resources"] = terraform_resources
    if terraform_modules:
        infrastructure["terraform_modules"] = terraform_modules
    if terraform_variables:
        infrastructure["terraform_variables"] = terraform_variables
    if terraform_outputs:
        infrastructure["terraform_outputs"] = terraform_outputs
    if argocd_apps:
        infrastructure["argocd_applications"] = argocd_apps
    if argocd_appsets:
        infrastructure["argocd_applicationsets"] = argocd_appsets
    if crossplane_xrds:
        infrastructure["crossplane_xrds"] = crossplane_xrds
    if crossplane_compositions:
        infrastructure["crossplane_compositions"] = crossplane_compositions
    if crossplane_claims:
        infrastructure["crossplane_claims"] = crossplane_claims
    if helm_charts:
        infrastructure["helm_charts"] = helm_charts
    if helm_values:
        infrastructure["helm_values"] = helm_values
    if kustomize_overlays:
        infrastructure["kustomize_overlays"] = kustomize_overlays
    if terragrunt_configs:
        infrastructure["terragrunt_configs"] = terragrunt_configs

    # Build ecosystem section
    ecosystem: dict[str, Any] | None = None
    if tier or (deps and deps["dependencies"]) or (
        dependents and dependents["dependents"]
    ):
        ecosystem = {
            "tier": tier["tier"] if tier else None,
            "risk_level": tier["risk_level"] if tier else None,
            "dependencies": deps["dependencies"] if deps else [],
            "dependents": (
                dependents["dependents"] if dependents else []
            ),
        }

    return {
        "repository": {
            "name": repo["name"],
            "path": repo["path"],
            "file_count": len(file_stats),
            "files_by_extension": ext_counts,
        },
        "code": {
            "functions": code_stats["functions"] if code_stats else 0,
            "classes": code_stats["classes"] if code_stats else 0,
            "languages": languages,
            "entry_points": entry_points,
        },
        "infrastructure": infrastructure,
        "relationships": relationships,
        "ecosystem": ecosystem,
    }
