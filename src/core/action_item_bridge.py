"""Action item bridge: detect -> dedup -> Neo4j save (KIK-472).

Orchestrates the full action item pipeline. Graceful degradation on any failure.

KIK-513: process_action_items() accepts optional ``graph_writer`` (GraphWriter
Protocol) for dependency injection. When omitted, falls back to importing
graph_store functions directly (backward compatible).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.ports.graph import GraphWriter


def process_action_items(
    suggestions: list[dict],
    health_data: dict | None = None,
    context: dict | None = None,
    *,
    graph_writer: GraphWriter | None = None,
) -> list[dict]:
    """Detect action items, deduplicate them, and save new items to Neo4j.

    Args:
        suggestions: Output from proactive_engine.get_suggestions().
        health_data: Output from health_check.run_health_check() (optional).
        context: Graph context dict (optional).
        graph_writer: Optional GraphWriter Protocol instance (KIK-513 DIP).
            When None, falls back to importing graph_store functions directly.

    Returns:
        List of created action items with results:
        [{action_id, title, symbol, neo4j_saved}]
    """
    try:
        from src.core.action_item_detector import detect_action_items
    except ImportError:
        return []

    try:
        items = detect_action_items(suggestions, health_data, context)
    except Exception:
        return []

    if not items:
        return []

    today = date.today().isoformat()
    results: list[dict] = []

    # KIK-489: Derive HealthCheck source_node_id for TRIGGERED relationship
    source_node_id = None
    if health_data:
        health_date = health_data.get("date", today)
        source_node_id = f"health_{health_date}"

    for item in items:
        try:
            action_id = item.get("action_id", "")
            title = item.get("title", "")
            symbol = item.get("symbol", "")
            trigger_type = item.get("trigger_type", "")
            urgency = item.get("urgency", "medium")

            result_entry: dict = {
                "action_id": action_id,
                "title": title,
                "symbol": symbol,
                "neo4j_saved": False,
            }

            # 1. Dedup check via Neo4j
            if _is_duplicate_neo4j(action_id, graph_writer=graph_writer):
                continue

            # 2. Save to Neo4j (with TRIGGERED relationship from HealthCheck)
            neo4j_saved = _save_to_neo4j(
                action_id=action_id,
                action_date=today,
                trigger_type=trigger_type,
                title=title,
                symbol=symbol,
                urgency=urgency,
                source_node_id=source_node_id,
                graph_writer=graph_writer,
            )
            result_entry["neo4j_saved"] = neo4j_saved

            results.append(result_entry)
        except Exception:
            continue  # graceful degradation per item

    return results


def _is_duplicate_neo4j(
    action_id: str,
    *,
    graph_writer: GraphWriter | None = None,
) -> bool:
    """Check if an action item with this ID already exists and is open."""
    try:
        if graph_writer is not None:
            existing = graph_writer.get_open_action_items()  # type: ignore[attr-defined]
        else:
            from src.data.graph_store import get_open_action_items
            existing = get_open_action_items()
        return any(item.get("id") == action_id for item in existing)
    except Exception:
        return False


def _save_to_neo4j(
    action_id: str,
    action_date: str,
    trigger_type: str,
    title: str,
    symbol: str,
    urgency: str,
    source_node_id: str | None = None,
    *,
    graph_writer: GraphWriter | None = None,
) -> bool:
    """Save action item to Neo4j with optional TRIGGERED relationship (KIK-489)."""
    try:
        if graph_writer is not None:
            return graph_writer.merge_action_item(
                action_id=action_id,
                action_date=action_date,
                trigger_type=trigger_type,
                title=title,
                symbol=symbol,
                urgency=urgency,
                source_node_id=source_node_id,
            )
        from src.data.graph_store import merge_action_item
        return merge_action_item(
            action_id=action_id,
            action_date=action_date,
            trigger_type=trigger_type,
            title=title,
            symbol=symbol,
            urgency=urgency,
            source_node_id=source_node_id,
        )
    except Exception:
        return False
