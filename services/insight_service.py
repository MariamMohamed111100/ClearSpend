import json
import os
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()


def _normalize_categories(categories: Any) -> dict[str, Any]:
    if isinstance(categories, dict):
        return categories
    if isinstance(categories, str):
        try:
            parsed = json.loads(categories)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _normalize_transactions(transactions: Any) -> list[Any]:
    if isinstance(transactions, list):
        return transactions
    if isinstance(transactions, str):
        try:
            parsed = json.loads(transactions)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []
    return []


def build_finance_prompt(user_input: str, monthly_income: Any, categories: Any, recent_transactions: Any) -> str:
    normalized_categories = _normalize_categories(categories)
    normalized_transactions = _normalize_transactions(recent_transactions)

    return f"""You are an AI financial assistant helping users manage their budgets and improve cash flow.

User goal:
{user_input}

Relevant financial data:
- Monthly Income: {monthly_income}
- Spending Categories (Last Month): {json.dumps(normalized_categories, ensure_ascii=False, indent=2)}
- Recent Transactions: {json.dumps(normalized_transactions, ensure_ascii=False, indent=2)}

Generate a concise and motivating insight that:
1. Highlights any spending trends or overspending patterns.
2. Recommends a practical action the user can take this month.
3. Uses a confident and encouraging tone.
4. Mentions realistic savings or budget improvements when relevant.
5. Keeps the final answer in one polished paragraph.

Return only the final answer text, no markdown block or JSON wrapper.
"""


def generate_financial_insight(user_input: str, monthly_income: Any, categories: Any, recent_transactions: Any) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    client = genai.Client(api_key=api_key)
    prompt = build_finance_prompt(user_input, monthly_income, categories, recent_transactions)

    response = client.models.generate_content(
        model=model_name,
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.5,
            top_p=0.95,
            top_k=40,
            max_output_tokens=1024,
            response_mime_type="text/plain",
        ),
    )

    raw_text = getattr(response, "text", "") or ""
    if not raw_text:
        return "I could not generate a financial insight right now. Please try again."

    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned.replace("```json", "", 1).replace("```", "", 1).strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```", "", 1).strip()

    cleaned = cleaned.replace("—", "-").replace("–", "-").replace("―", "-").replace("−", "-").replace("‒", "-")
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            if isinstance(payload.get("response"), str):
                return payload["response"].replace("—", "-").replace("–", "-").replace("―", "-")
            if isinstance(payload.get("insight"), str):
                return payload["insight"].replace("—", "-").replace("–", "-").replace("―", "-")
    except (TypeError, ValueError):
        pass

    return cleaned
