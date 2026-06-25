"""Throwaway: drive the 3 LLM tools through MCP, chaining the GapAnalysis object."""
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

JOB_TITLE = "AI Engineer"
JOB_DESC = (
    "We're hiring an AI Engineer to build LLM-powered features. You'll design RAG "
    "pipelines, deploy models behind FastAPI services, work with vector databases, "
    "and own evaluation and observability. Required: Python, LLMs/prompt engineering, "
    "retrieval-augmented generation, Docker, and cloud deployment (AWS). Nice to have: "
    "LangGraph/agent frameworks, fine-tuning, and CI/CD for ML."
)


async def main():
    params = StdioServerParameters(
        command="python3", args=["-m", "app.mcp_server"], cwd="/workspace",
        env={"PYTHONPATH": "/workspace", "PATH": "/usr/local/bin:/usr/bin:/bin"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("CALL analyze_gap")
            r = await session.call_tool("analyze_gap", {"job_title": JOB_TITLE, "job_description": JOB_DESC})
            gap = r.structuredContent
            print("  isError:", r.isError, "| fit_score:", gap.get("fit_score"),
                  "| assessments:", len(gap.get("assessments", [])))
            print("  summary:", (gap.get("summary") or "")[:160])

            print("\nCALL suggest_projects(gap)  <- chaining the gap object back in")
            r = await session.call_tool("suggest_projects", {"gap": gap})
            proj = r.structuredContent
            print("  isError:", r.isError, "| suggestions:", len(proj.get("suggestions", [])))
            for p in proj.get("suggestions", [])[:3]:
                print(f"    - {p.get('title')} [{p.get('difficulty')}]")

            print("\nCALL generate_interview_questions(gap)")
            r = await session.call_tool("generate_interview_questions", {"gap": gap})
            kit = r.structuredContent
            qs = kit.get("questions", [])
            print("  isError:", r.isError, "| questions:", len(qs))
            for q in qs[:3]:
                print(f"    - [{q.get('category')}] {(q.get('question') or '')[:90]}")


if __name__ == "__main__":
    asyncio.run(main())