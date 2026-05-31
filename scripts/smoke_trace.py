"""Phase A smoke test: fire one LLM call and confirm it lands in Langfuse.

Run from inside the app container:
    docker compose -f docker/docker-compose.yml exec app python3 scripts/smoke_trace.py
"""
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.observability.langfuse_client import (
    get_langchain_callback,
    get_langfuse,
    shutdown_langfuse,
)


def main() -> None:
    settings = get_settings()

    # Sanity output
    print(f"OpenAI model: {settings.openai_model}")
    print(f"Langfuse host: {settings.langfuse_host}")
    print(f"Langfuse enabled: {settings.langfuse_enabled}")

    if not settings.langfuse_enabled:
        raise SystemExit("Langfuse keys missing — set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY in .env")

    callback = get_langchain_callback()
    callbacks = [callback] if callback else []

    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )

    prompt = "In exactly five words, greet a new AI engineering job seeker."
    print(f"\nPrompt: {prompt}")
    result = llm.invoke(prompt, config={"callbacks": callbacks, "run_name": "phase-a-smoke-test"})
    print(f"Response: {result.content}")

    # Flush queued events synchronously so the trace lands before we exit.
    shutdown_langfuse()
    print("\nDone. Open http://localhost:3000 → Traces → look for 'phase-a-smoke-test'")


if __name__ == "__main__":
    main()
