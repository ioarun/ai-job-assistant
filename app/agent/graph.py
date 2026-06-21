"""Assemble the Phase D agent graph and compile it with a SQLite checkpointer.

Topology (docs/phase-d-theory.md, Step 2):

    START -> planner -> tool_router --(next tool)--> tool_executor --+
                              |                                       |
                        (plan done)                                  | loop
                              v                                       |
                          reflector -> responder -> END   <----tool_router

The checkpointer persists state after every super-step keyed by thread_id, which is
what makes short-term memory, durability, and HITL pause/resume work (Step 5).
"""
from contextlib import asynccontextmanager

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    planner, reflector, responder, route_from_router, tool_executor, tool_router,
)
from app.agent.state import AgentState, JobView
from app.models.analysis import GapAnalysis, InterviewKit, ProjectSuggestions

CHECKPOINT_DB = "data/agent_checkpoints.sqlite"

# Types the checkpointer is allowed to (de)serialize from msgpack. LangGraph warns —
# and will eventually block — deserializing unregistered classes; declaring ours here
# future-proofs the checkpoint format.
ALLOWED_MSGPACK_TYPES = [JobView, GapAnalysis, ProjectSuggestions, InterviewKit]


def build_graph(checkpointer=None):
    """Wire nodes + edges and compile. Pass a checkpointer for persistence/HITL."""
    g = StateGraph(AgentState)
    g.add_node("planner", planner)
    g.add_node("tool_router", tool_router)
    g.add_node("tool_executor", tool_executor)
    g.add_node("reflector", reflector)
    g.add_node("responder", responder)

    g.add_edge(START, "planner")
    g.add_edge("planner", "tool_router")
    g.add_conditional_edges(
        "tool_router", route_from_router,
        {"tool_executor": "tool_executor", "reflector": "reflector"},
    )
    g.add_edge("tool_executor", "tool_router")  # loop back until plan is satisfied
    g.add_edge("reflector", "responder")
    g.add_edge("responder", END)

    return g.compile(checkpointer=checkpointer)


@asynccontextmanager
async def open_graph(db_path: str = CHECKPOINT_DB):
    """Yield a compiled graph backed by an AsyncSqliteSaver (file-persisted).

    We build the saver by hand (rather than AsyncSqliteSaver.from_conn_string) so we
    can pass a serde with our allowed msgpack types.
    """
    serde = JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_TYPES)
    async with aiosqlite.connect(db_path) as conn:
        saver = AsyncSqliteSaver(conn, serde=serde)
        yield build_graph(saver)