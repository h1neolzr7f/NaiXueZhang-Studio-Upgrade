# File ownership and leases

Base SHA: `008de38ad4dc6c8afbf0ec32ae411cd85685ac02`

| path/glob | owner | purpose | acquired_at | expected_release | shared_interface |
|---|---|---|---|---|---|
| butler/store.py | Lead | durable tasks/events/receipts | 2026-08-15 | after v1.8 gate | receipts, unknown isolation |
| butler/workflow_runtime.py | Lead | LangGraph runtime | 2026-08-15 | after v1.8 gate | confirm/interrupt |
| butler/planning.py | Lead | one-shot planner | 2026-08-15 | after v1.8 gate | plan JSON |
| butler/agents.py | Lead | desk allow-lists | 2026-08-15 | after v1.8 gate | reject_foreign_tool |
| data/butler_catalog.json | Lead | tool catalog | 2026-08-15 | after v1.8 gate | risk labels |
| LICENSE / VERSION / release scripts | Lead | license and release | 2026-08-15 | standing | none |
| nai/ nai_api.py nai_char_modules/ | W1 | NAI compile/transport | 2026-08-15 | v1.6 | generate_image |
| gallery_*.py db.py db_queries.py search.py generated_gallery.py | W2 | gallery assets | 2026-08-15 | v1.7 | WorkRef, search_works |
| butler/tooling/ tests/tooling/ | W3 | independent kernel | 2026-08-15 | v1.8 integration | WorkflowRequest |
| butler/tooling/catalog_projection.py | W3 | read-only catalog projection | 2026-08-15 | v1.8 integration | ToolSpec |
| tests/ scripts/*windows*.ps1 scripts/bench_gallery.py scripts/check_windows_scripts.py docs/top-tier-upgrade/ | W4 / Lead | quality and handoff | 2026-08-15 | standing | doctor/verify |
| .cursor/environment.json | Lead | Cloud install baseline | 2026-08-15 | standing | core lock + pytest + langgraph |
| frontend/ web/ | shared read; UI owners per change | dual UI | 2026-08-15 | per PR | same API |

Workers must not edit another lease. Propose patches to Lead instead.
