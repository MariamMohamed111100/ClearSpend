import base64
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

def generate(user_input, monthly_income, categories, recent_transactions):
    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY"),
    )

    model = "gemini-2.0-flash"

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=user_input)],
        ),
        types.Content(
            role="model",
            parts=[types.Part.from_text(text="""```json
{
  "response": "Hey there! 👋 Let's take a peek at your spending. I'll need a bit more info about your income, spending categories, and recent transactions to give you personalized insights. Once I have that, I can highlight any trends and offer some friendly tips to help you reach your financial goals! 🚀"
}
```""")],
        ),
        types.Content(
            role="user",
            parts=[types.Part.from_text(text="""INSERT_INPUT_HERE""")],
        ),
    ]

    # Define the system instructions
    generate_content_config = types.GenerateContentConfig(
        temperature=0.5,
        top_p=0.95,
        top_k=40,
        max_output_tokens=8192,
        response_mime_type="application/json",
        response_schema=genai.types.Schema(
            type=genai.types.Type.OBJECT,
            properties={"response": genai.types.Schema(type=genai.types.Type.STRING)},
        ),
        system_instruction=[types.Part.from_text(text=f"""You are an AI financial assistant helping users manage their budgets.
Based on the following user data, provide a short, engaging insight with suggestions:

- *Monthly Income:* {monthly_income}
- *Spending Categories (Last Month):* {categories}
- *Recent Transactions:* {recent_transactions}

Generate insights that:
1. Highlight spending trends (e.g., overspending in a category).
2. Offer a *personalized* suggestion (e.g., "Try saving 10% more in X category").
3. Use a *friendly, motivating tone* to engage the user.

Example output:
Hey Alex! 🎯 You spent 30% of your budget on entertainment this month—maybe swap a few movie nights for game nights at home? You could save *EGP 300* and put it towards your travel fund! 🚀""")],
    )

    # Make the API call to generate content
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=generate_content_config,
    )

    return response.text  # Return the generated response
