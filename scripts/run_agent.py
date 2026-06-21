#!/usr/bin/env python3
"""Drive the Phase D LangGraph agent end to end (core graph; no SSE yet).

Streams node-by-node progress, pauses for human approval before a LIVE Adzuna call
(dynamic interrupt), resumes via Command(resume=...), and prints the final answer.
The run is checkpointed to SQLite keyed by --thread, so re-running the same thread
reuses the conversation (short-term memory) and the Adzuna cache.

Requires the stack configured (OpenAI key, a resume indexed) and langgraph installed.

Usage:
    python -m scripts.run_agent "find 3 AU AI engineering jobs, analyse my gaps for the top one, suggest a project"
    python -m scripts.run_agent "..." --thread demo1 --auto-approve
"""
import argparse
import asyncio
import logging
import sys

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.graph import open_graph
from app.core.logging import configure_logging
from app.observability.langfuse_client import shutdown_langfuse


def _print_updates(chunk: dict) -> None:
    """Print any new AI/progress messages emitted by a node this super-step."""
    for node, update in chunk.items():
        if not isinstance(update, dict):
            continue
        for msg in update.get("messages", []) or []:
            if isinstance(msg, AIMessage) and msg.content:
                print(f"  [{node}] {msg.content}")


async def _approve(payload: dict, auto: bool) -> bool:
    print("\n⏸  APPROVAL NEEDED")
    print(f"    {payload.get('reason')}")
    print(f"    search: what={payload.get('what')!r} where={payload.get('where')!r}")
    if auto:
        print("    (--auto-approve) → approving")
        return True
    ans = await asyncio.to_thread(input, "    approve live search? [y/N] ")
    return ans.strip().lower() in ("y", "yes")


async def run(request: str, thread_id: str, auto: bool) -> int:
    config = {"configurable": {"thread_id": thread_id}}
    payload_in = {"messages": [HumanMessage(content=request)]}

    async with open_graph() as graph:
        while True:
            interrupted = False
            async for chunk in graph.astream(payload_in, config, stream_mode="updates"):
                if "__interrupt__" in chunk:
                    decision = await _approve(chunk["__interrupt__"][0].value, auto)
                    payload_in = Command(resume={"approved": decision})
                    interrupted = True
                    break
                _print_updates(chunk)
            if not interrupted:
                break

        state = await graph.aget_state(config)

    print("\n" + "=" * 70 + "\nFINAL ANSWER\n" + "=" * 70)
    print(state.values.get("final_answer", "(no answer produced)"))
    shutdown_langfuse()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase D LangGraph agent.")
    parser.add_argument("request", help="Natural-language request for the agent")
    parser.add_argument("--thread", default="cli-demo", help="thread_id (conversation/checkpoint key)")
    parser.add_argument("--auto-approve", action="store_true", help="Approve live Adzuna calls without prompting")
    args = parser.parse_args()

    configure_logging()
    sys.exit(asyncio.run(run(args.request, args.thread, args.auto_approve)))


if __name__ == "__main__":
    main()