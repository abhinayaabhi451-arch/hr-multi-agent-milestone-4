import os
import logging
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

logging.getLogger("google_genai").setLevel(logging.ERROR)
logging.getLogger("langchain_google_genai").setLevel(logging.ERROR)

load_dotenv()

# Defaults to a "lite" model, which typically carries a much higher
# free-tier daily quota than the full "flash" models. Override by
# setting GEMINI_MODEL in .env if you want to pin a specific model
# (e.g. after checking current limits at
# https://ai.google.dev/gemini-api/docs/rate-limits).
DEFAULT_MODEL = "gemini-flash-lite-latest"


def get_llm():
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


def extract_text(content) -> str:
    """Newer Gemini models return content as a list of structured
    blocks instead of a plain string. This pulls out just the text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
            elif hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts)
    return str(content)
