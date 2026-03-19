# Patch Notes: Git-Boundary-Aware Parent Directory Indexing

## Upstream

- **Repository**: [CodeGraphContext/CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext)
- **Pinned Version**: v0.3.1 (commit `3f78184`)
- **Fork**: [linuxdynasty/CodeGraphContext](https://github.com/linuxdynasty/CodeGraphContext)

## Problem

When deploying CGC to index 900+ organization repos, there are two approaches — each with a critical limitation:

1. **Per-repo indexing** (`cgc index /data/repos/repo-a`, then `repo-b`, etc.):
   - Creates correct per-repo Repository nodes
   - But `imports_map` is rebuilt per invocation, so cross-repo call resolution fails

2. **Parent directory indexing** (`cgc index /data/repos/`):
   - Builds ONE unified `imports_map` across all files — cross-repo resolution works
   - But creates a single Repository node for the parent directory, losing per-repo identity

## Solution

Patch `build_graph_from_path_async` in `graph_builder.py` to detect `.git/` boundaries inside a parent directory:

- Walk up from each discovered file to find its nearest `.git/` directory
- Create separate Repository nodes for each git sub-repo
- Build ONE unified `imports_map` across all files (unchanged)
- Route each file to its correct Repository node during graph construction

This gives us **both** per-repo identity **and** cross-repo resolution.

## What Changed

### `src/codegraphcontext/tools/graph_builder.py`

**Method**: `build_graph_from_path_async`

1. **Removed** premature single `add_repository_to_graph(path)` call
2. **Added** git-boundary detection loop after file discovery/filtering:
   - Builds `git_repos` dict mapping each repo root to its files
   - Builds `file_to_repo` dict for O(1) file→repo lookup
3. **Added** per-repo Repository node creation from `git_repos`
4. **Modified** file processing loop to use `file_to_repo` lookup instead of hardcoded parent path

### `Dockerfile`

- Added `jq` and `gh` CLI to runtime dependencies (needed by repo sync scripts)

## How to Upgrade When Upstream Releases a New Version

1. Add upstream remote: `git remote add upstream https://github.com/CodeGraphContext/CodeGraphContext.git`
2. Fetch upstream: `git fetch upstream`
3. Merge upstream tag: `git merge v0.X.Y`
4. Resolve conflicts in `graph_builder.py` — the patch is localized to `build_graph_from_path_async`
5. Run verification queries (below)
6. Build and push new image

## Verification

### Neo4j Queries

```cypher
-- Should show N repos, not 1 parent directory
MATCH (r:Repository) RETURN r.name, r.path ORDER BY r.name LIMIT 20

-- Functions should be linked to correct repos
MATCH (r:Repository)-[:CONTAINS*]->(f:Function)
RETURN r.name, count(f) ORDER BY count(f) DESC LIMIT 20

-- Cross-repo call resolution (the key benefit)
MATCH (caller:Function)-[:CALLS]->(callee:Function),
      (r1:Repository)-[:CONTAINS*]->(caller),
      (r2:Repository)-[:CONTAINS*]->(callee)
WHERE r1 <> r2
RETURN r1.name, caller.name, r2.name, callee.name LIMIT 10
```

### MCP Tool Queries

```
list_indexed_repositories()        -- Should return 900+ repos
find_code("processPayment")       -- Results across multiple repos
analyze_code_relationships(        -- Cross-repo callers
  query_type="find_callers",
  target="someSharedFunction"
)
```
