# Project Guidelines & Codebase Intelligence

## Mandatory: Codebase Analysis via Graphify Knowledge Graph

Whenever analyzing this codebase, investigating system architecture, tracing data flows or call hierarchies, exploring dependencies, or answering questions about how components connect:

1. **Always consult the Graphify knowledge graph first**:
   - Check `graphify-out/graph.json` and `graphify-out/GRAPH_REPORT.md` before doing raw file searches.
   - Use the graphify CLI / traversal tools:
     - `graphify query "<question>"` for structural context and conceptual navigation.
     - `graphify path "<source>" "<target>"` for shortest dependency and call paths between subsystems.
     - `graphify explain "<node>"` for plain-language node breakdown and connections.
2. **Leverage Core God Nodes & Community Hubs**:
   - Key system bridge nodes (`IBKRClient`, `compute_composite_score`, `job_pre_market_scan`, `compute_regime_status`, `Trade`, `get_setting`) connect multiple isolated communities. Always check their cross-community edges before modifying interfaces.
3. **Keep the Graph in Sync**:
   - After substantial architectural changes or new modules, run `/graphify --update` to re-extract modified files so the knowledge graph stays aligned with the code.
