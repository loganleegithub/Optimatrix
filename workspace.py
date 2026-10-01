"""Read-only business view of saved S3 research; no account or order authority."""
from __future__ import annotations

import copy

from market import iso
from research import ACTIVE


def _result(task):
    presentation = task.get("final_presentation")
    if task.get("status") != "completed" or not presentation:
        return None
    validation = presentation.get("validation") or {}
    # Evidence IDs come from records actually read by the deterministic tools,
    # never from the model's unverified prose or experiment declarations.
    evidence_ids = list(dict.fromkeys(
        item["run_id"] for item in task.get("evidence", []) if item.get("run_id")
    ))
    return {
        "research_id": task["research_id"],
        "verdict": presentation.get("verdict"),
        "validation_status": validation.get("status", "unknown"),
        "validation_scope": validation.get("scope"),
        "evidence_run_ids": evidence_ids,
        "href": "/research?research_id=" + task["research_id"],
        "created_at": task.get("created_at"),
    }


def _agent(task, active_id):
    config = task.get("configuration_snapshot") or {}
    role = config.get("role") or "researcher"
    actions = task.get("actions") or []
    active = task["research_id"] == active_id and task.get("status") in ACTIVE
    return {
        "agent_id": role + ":" + task["research_id"],
        "research_id": task["research_id"],
        "role": role,
        "model": config.get("model"),
        "reasoning_effort": config.get("reasoning_effort"),
        "prompt_version": config.get("prompt_version"),
        "schema_version": config.get("output_schema_version"),
        "status": task.get("status"),
        "is_active": active,
        "question": task.get("question"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "inputs": {
            "references": copy.deepcopy(task.get("input_references") or []),
            "available_run_ids": copy.deepcopy(task.get("available_run_ids") or []),
            "read_run_ids": list(dict.fromkeys(
                action["run_id"] for action in actions
                if action.get("action") == "read_result"
                and action.get("status") == "done" and action.get("run_id")
            )),
            "evidence_run_ids": list(dict.fromkeys(
                item["run_id"] for item in task.get("evidence", []) if item.get("run_id")
            )),
            "scope": "保存的模型输入快照；可用历史、显式读取与工具取得的结果摘要分别列示。逐事件原始行未送入模型，不证明模型逐行阅读。",
        },
        "actions": [{
            "step": action.get("step"), "action": action.get("action"),
            "status": action.get("status"), "run_id": action.get("run_id"),
            "created_at": action.get("created_at"),
            "explanation": action.get("model_explanation"),
        } for action in actions],
        "budget": {key: task.get("budget", {}).get(key) for key in (
            "model_calls_used", "model_calls_limit", "backtest_creations_used", "backtest_creations_limit"
        )},
        "result": _result(task),
        "failure": None if task.get("status") == "completed" else task.get("error"),
        "href": "/research?research_id=" + task["research_id"],
    }


def workspace_snapshot(research):
    """Aggregate one consistent cached research snapshot without launching work."""
    if research is None:
        runs, active_id, configured = [], None, {}
        availability = {"ready": False, "reason": "研究后端未启用"}
        storage_error = "研究后端未启用"
    else:
        # list_runs/detail derive evidence presentation without writing history.
        # Keep ownership, task state and configuration consistent under its RLock.
        # Do not call config_snapshot: it adds unrelated tool/config information.
        with research.lock:
            runs = research.list_runs()["runs"]
            active_id = research.active_id
            configured = copy.deepcopy(research.configuration)
            availability = {key: copy.deepcopy(research.availability.get(key)) for key in ("ready", "reason")}
            storage_error = research.storage_error

    runs = sorted(runs, key=lambda task: task.get("created_at") or "", reverse=True)
    agents = [_agent(task, active_id) for task in runs]
    conclusions = []
    for agent in agents:
        if agent["result"] is None:
            continue
        candidate = copy.deepcopy(agent["result"])
        if candidate["validation_status"] != "passed":
            candidate["status"] = "validation_gaps"
        else:
            candidate["status"] = {
                "值得继续": "research_candidate", "否定候选": "rejected", "数据不足": "inconclusive"
            }.get(candidate["verdict"], "inconclusive")
        conclusions.append(candidate)

    return {
        "server_time": iso(),
        "stage": "S3",
        "account": {
            "status": "not_connected", "unit": "BTC", "source_at": None,
            "net_equity_btc": None, "realized_pnl_btc": None, "open_risk_btc": None,
            "premium_budget_remaining_btc": None, "reason": "未接入真实账户",
        },
        "strategy": {
            "status": "not_authorized", "version": None, "positions": None, "exit_schedule": None,
            "entry_blocker": "S3 未获交易授权，未接入真实账户或持仓",
            "latest_candidate": conclusions[0] if conclusions else None,
            "candidate_count": sum(item["status"] == "research_candidate" for item in conclusions),
        },
        "agents": {
            "active": [agent for agent in agents if agent["is_active"]],
            "history": [agent for agent in agents if not agent["is_active"]],
            "configured": {key: configured.get(key) for key in ("role", "model", "reasoning_effort")},
            "availability": availability, "storage_error": storage_error,
        },
        "approvals": {
            "pending": [], "strategy_approval_status": "requires_s4_authorization",
            "scope": "S3 研究预算",
            "effect": "仅启动一次有上限的回测研究；不改变策略、持仓或交易权限",
            "research_start_endpoint": "/api/research/start",
        },
    }
