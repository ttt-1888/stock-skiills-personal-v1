"""Save health check results to history (KIK-578 split from save.py)."""

from datetime import date, datetime

from src.data.history._helpers import (
    _history_dir,
    _write_json_atomic,
    _dual_write_graph,
)


def save_health(
    health_data: dict,
    base_dir: str = "data/history",
    sync_external: bool = False,
) -> str:
    """Save health check results to JSON.

    Returns the absolute path of the saved file.
    """
    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    filename = f"{today}_health.json"

    positions_out = []
    for pos in health_data.get("positions", []):
        positions_out.append({
            "symbol": pos.get("symbol"),
            "pnl_pct": pos.get("pnl_pct"),
            "trend": pos.get("trend_health", {}).get("trend", "不明"),
            "quality_label": pos.get("change_quality", {}).get("quality_label", "-"),
            "alert_level": pos.get("alert", {}).get("level", "none"),
        })

    summary_raw = health_data.get("summary", {})
    summary = {
        "total": summary_raw.get("total", len(positions_out)),
        "healthy": summary_raw.get("healthy", 0),
        "early_warning": summary_raw.get("early_warning", 0),
        "caution": summary_raw.get("caution", 0),
        "exit": summary_raw.get("exit", 0),
    }

    payload = {
        "category": "health",
        "date": today,
        "timestamp": now,
        "summary": summary,
        "positions": positions_out,
        "_saved_at": now,
    }

    d = _history_dir("health", base_dir)
    path = d / filename
    _write_json_atomic(path, payload)

    if not sync_external:
        return str(path.resolve())

    symbols = [p.get("symbol") for p in health_data.get("positions", []) if p.get("symbol")]

    def _graph_write(sem_summary, emb):
        from src.data.graph_store import merge_health
        merge_health(today, summary, symbols,
                     semantic_summary=sem_summary, embedding=emb)

    _dual_write_graph(
        _graph_write, "health",
        dict(date=today, summary=summary),
    )

    return str(path.resolve())
