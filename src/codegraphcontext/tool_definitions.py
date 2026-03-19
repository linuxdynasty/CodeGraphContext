
TOOLS = {
    "add_code_to_graph": {
        "name": "add_code_to_graph",
        "description": "Performs a one-time scan of a local folder to add its code to the graph. Ideal for indexing libraries, dependencies, or projects not being actively modified. Returns a job ID for background processing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the directory or file to add."},
                "is_dependency": {"type": "boolean", "description": "Whether this code is a dependency.", "default": False}
            },
            "required": ["path"]
        }
    },
    "check_job_status": {
        "name": "check_job_status",
        "description": "Check the status and progress of a background job.",
        "inputSchema": {
            "type": "object",
            "properties": { "job_id": {"type": "string", "description": "Job ID from a previous tool call"} },
            "required": ["job_id"]
        }
    },
    "list_jobs": {
        "name": "list_jobs",
        "description": "List all background jobs and their current status.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    "find_code": {
        "name": "find_code",
        "description": "Find relevant code snippets related to a keyword (e.g., function name, class name, or content).",
        "inputSchema": {
            "type": "object",
            "properties": { "query": {"type": "string", "description": "Keyword or phrase to search for"}, "fuzzy_search": {"type": "boolean", "description": "Whether to use fuzzy search", "default": False}, "edit_distance": {"type": "number", "description": "Edit distance for fuzzy search (between 0-2)", "default": 2}, "repo_path": {"type": "string", "description": "Optional: Path to the repository to restrict the search to."}}, 
            "required": ["query"]
        }
    },
    "analyze_code_relationships": {
        "name": "analyze_code_relationships",
        "description": "Analyze code relationships like 'who calls this function' or 'class hierarchy'. Supported query types include: find_callers, find_callees, find_all_callers, find_all_callees, find_importers, who_modifies, class_hierarchy, overrides, dead_code, call_chain, module_deps, variable_scope, find_complexity, find_functions_by_argument, find_functions_by_decorator.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_type": {"type": "string", "description": "Type of relationship query to run.", "enum": ["find_callers", "find_callees", "find_all_callers", "find_all_callees", "find_importers", "who_modifies", "class_hierarchy", "overrides", "dead_code", "call_chain", "module_deps", "variable_scope", "find_complexity", "find_functions_by_argument", "find_functions_by_decorator"]},
                "target": {"type": "string", "description": "The function, class, or module to analyze."},
                "context": {"type": "string", "description": "Optional: specific file path for precise results."},
                "repo_path": {"type": "string", "description": "Optional: Path to the repository to restrict the search to."}
            },
            "required": ["query_type", "target"]
        }
    },
    "watch_directory": {
        "name": "watch_directory",
        "description": "Performs an initial scan of a directory and then continuously monitors it for changes, automatically keeping the graph up-to-date. Ideal for projects under active development. Returns a job ID for the initial scan.",
        "inputSchema": {
            "type": "object",
            "properties": { "path": {"type": "string", "description": "Path to directory to watch"} },
            "required": ["path"]
        }
    },
    "execute_cypher_query": {
        "name": "execute_cypher_query",
        "description": "Fallback tool to run a direct, read-only Cypher query against the code graph. Use this for complex questions not covered by other tools. The graph contains nodes representing code structures and relationships between them. **Schema Overview:**\n- **Nodes:** `Repository`, `File`, `Module`, `Class`, `Function`.\n- **Properties:** Nodes have properties like `name`, `path`, `cyclomatic_complexity` (on Function nodes), and `source`.\n- **Relationships:** `CONTAINS` (e.g., File-[:CONTAINS]->Function), `CALLS` (Function-[:CALLS]->Function or File-[:CALLS]->Function), `IMPORTS` (File-[:IMPORTS]->Module), `INHERITS` (Class-[:INHERITS]->Class).",
        "inputSchema": {
            "type": "object",
            "properties": { "cypher_query": {"type": "string", "description": "The read-only Cypher query to execute."} },
            "required": ["cypher_query"]
        }
    },
    "add_package_to_graph": {
        "name": "add_package_to_graph",
        "description": "Add a package to the graph by discovering its location. Supports multiple languages. Returns immediately with a job ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_name": {"type": "string", "description": "Name of the package to add (e.g., 'requests', 'express', 'moment', 'lodash')."},
                "language": {"type": "string", "description": "The programming language of the package.", "enum": ["python", "javascript", "typescript", "java", "c", "go", "ruby", "php","cpp"]},
                "is_dependency": {"type": "boolean", "description": "Mark as a dependency.", "default": True}
            },
            "required": ["package_name", "language"]
        }
    },
    "find_dead_code": {
        "name": "find_dead_code",
        "description": "Find potentially unused functions (dead code) across the entire indexed codebase, optionally excluding functions with specific decorators.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exclude_decorated_with": {"type": "array", "items": {"type": "string"}, "description": "Optional: A list of decorator names (e.g., '@app.route') to exclude from dead code detection.", "default": []},
                "repo_path": {"type": "string", "description": "Optional: Path to the repository to restrict the search to."}
            }
        }
    },
    "calculate_cyclomatic_complexity": {
        "name": "calculate_cyclomatic_complexity",
        "description": "Calculate the cyclomatic complexity of a specific function to measure its complexity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "function_name": {"type": "string", "description": "The name of the function to analyze."},
                "path": {"type": "string", "description": "Optional: The full path to the file containing the function for a more specific query."},
                "repo_path": {"type": "string", "description": "Optional: Path to the repository to restrict the search to."}
            },
            "required": ["function_name"]
        }
    },
    "find_most_complex_functions": {
        "name": "find_most_complex_functions",
        "description": "Find the most complex functions in the codebase based on cyclomatic complexity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "The maximum number of complex functions to return.", "default": 10},
                "repo_path": {"type": "string", "description": "Optional: Path to the repository to restrict the search to."}
            }
        }
    },
    "list_indexed_repositories": {
        "name": "list_indexed_repositories",
        "description": "List all indexed repositories.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    "delete_repository": {
        "name": "delete_repository",
        "description": "Delete an indexed repository from the graph.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "The path of the repository to delete."} 
            },
            "required": ["repo_path"]
        }
    },
    "visualize_graph_query": {
        "name": "visualize_graph_query",
        "description": "Generates a URL to visualize the results of a Cypher query in the Neo4j Browser. The user can open this URL in their web browser to see the graph visualization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cypher_query": {"type": "string", "description": "The Cypher query to visualize."}
            },
            "required": ["cypher_query"]
        }
    },
    "list_watched_paths": {
        "name": "list_watched_paths",
        "description": "Lists all directories currently being watched for live file changes.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    "unwatch_directory": {
        "name": "unwatch_directory",
        "description": "Stops watching a directory for live file changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The absolute path of the directory to stop watching."}
            },
            "required": ["path"]
        }
    },
    "load_bundle": {
        "name": "load_bundle",
        "description": "Load a pre-indexed .cgc bundle into the database. Can load from local file or automatically download from registry if not found locally. Bundles are portable snapshots of indexed code that load instantly without re-indexing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bundle_name": {"type": "string", "description": "Name of the bundle to load (e.g., 'flask', 'pandas', 'flask-main-2579ce9.cgc'). Can be a full filename or just the package name."},
                "clear_existing": {"type": "boolean", "description": "Whether to clear existing data before loading. Use with caution.", "default": False}
            },
            "required": ["bundle_name"]
        }
    },
    "search_registry_bundles": {
        "name": "search_registry_bundles",
        "description": "Search for available pre-indexed bundles in the registry. Returns bundles matching the search query with details like repository, version, size, and download information.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query to find bundles (searches in name, repository, and description). Leave empty to list all bundles."},
                "unique_only": {"type": "boolean", "description": "If true, show only the most recent version of each package. If false, show all versions.", "default": False}
            }
        }
    },
    "get_repository_stats": {
        "name": "get_repository_stats",
        "description": "Get statistics about indexed repositories, including counts of files, functions, classes, and modules. Can show overall database statistics or stats for a specific repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Optional: Path to a specific repository. If not provided, returns overall database statistics."}
            }
        }
    },
    # --- Ecosystem Tools ---
    "index_ecosystem": {
        "name": "index_ecosystem",
        "description": "Index all repositories in an ecosystem manifest (dependency-graph.yaml). Creates a unified graph across all repos with cross-repo relationships. Supports incremental updates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest_path": {"type": "string", "description": "Path to the ecosystem dependency-graph.yaml manifest file."},
                "base_path": {"type": "string", "description": "Base directory where repos are cloned locally."},
                "force": {"type": "boolean", "description": "Force re-index all repos regardless of state.", "default": False},
                "parallel": {"type": "integer", "description": "Max concurrent repo indexing.", "default": 4},
                "clone_missing": {"type": "boolean", "description": "Clone missing repos via gh CLI.", "default": False}
            },
            "required": ["manifest_path", "base_path"]
        }
    },
    "ecosystem_status": {
        "name": "ecosystem_status",
        "description": "Show the indexing status of all repos in the ecosystem. Shows which repos are indexed, stale, or failed.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    "get_ecosystem_overview": {
        "name": "get_ecosystem_overview",
        "description": "Get a high-level overview of the indexed ecosystem: repos, tiers, infrastructure counts, and cross-repo relationships. Use this instead of reading dependency-graph.yaml and browsing 20 repos.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    "trace_deployment_chain": {
        "name": "trace_deployment_chain",
        "description": "Trace the full deployment chain for a service: Repository -> ArgoCD Application -> K8s Resources -> Crossplane Claims -> XRDs -> Compositions, plus Terraform resources. Useful for incident investigation and impact analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Name of the service/repository to trace."}
            },
            "required": ["service_name"]
        }
    },
    "find_blast_radius": {
        "name": "find_blast_radius",
        "description": "Find all repos and resources affected by changing a target. Graph traversal of transitive dependencies to assess impact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Name of the target to analyze."},
                "target_type": {"type": "string", "description": "Type of target.", "enum": ["repository", "terraform_module", "crossplane_xrd"], "default": "repository"}
            },
            "required": ["target"]
        }
    },
    "find_infra_resources": {
        "name": "find_infra_resources",
        "description": "Search infrastructure resources (K8s, Terraform, ArgoCD, Crossplane, Helm) by name or type across all indexed repos.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for resource name or type."},
                "category": {"type": "string", "description": "Optional filter.", "enum": ["k8s", "terraform", "argocd", "crossplane", "helm"], "default": ""}
            },
            "required": ["query"]
        }
    },
    "analyze_infra_relationships": {
        "name": "analyze_infra_relationships",
        "description": "Analyze infrastructure relationships: what deploys what, what provisions what, who consumes this XRD, what uses this Terraform module.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_type": {"type": "string", "description": "Type of relationship query.", "enum": ["what_deploys", "what_provisions", "who_consumes_xrd", "module_consumers"]},
                "target": {"type": "string", "description": "Name of the target resource to analyze."}
            },
            "required": ["query_type", "target"]
        }
    },
    "get_repo_summary": {
        "name": "get_repo_summary",
        "description": "Get a structured summary of a repository: files, code entities, infrastructure resources, ecosystem connections, dependencies, and tier info.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of the repository."}
            },
            "required": ["repo_name"]
        }
    },
    "get_repo_context": {
        "name": "get_repo_context",
        "description": "Get complete context for a repository in a single call: files, code entities, all infrastructure resources, intra-repo relationships, and ecosystem info. Use as the FIRST call for any repo documentation or analysis task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name": {"type": "string", "description": "Name of the repository."}
            },
            "required": ["repo_name"]
        }
    },
}
