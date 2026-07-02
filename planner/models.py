import os
from langchain_openai import ChatOpenAI


class ChatOpenRouter(ChatOpenAI):
    """OpenRouter-compatible ChatOpenAI wrapper.

    Handles custom server-side tools (like openrouter:web_search) by binding them
    directly to model_kwargs to bypass standard OpenAI function-calling validation.
    """

    def __init__(self, **kwargs):
        # Default to OpenRouter endpoint and key if not specified
        kwargs.setdefault("openai_api_base", "https://openrouter.ai/api/v1")
        kwargs.setdefault("openai_api_key", os.environ.get("OPENROUTER_API_KEY"))
        super().__init__(**kwargs)

    def bind_tools(self, tools, **kwargs):
        openrouter_tools = []
        standard_tools = []
        for t in tools:
            if isinstance(t, dict) and str(t.get("type", "")).startswith("openrouter:"):
                openrouter_tools.append(t)
            else:
                standard_tools.append(t)

        if openrouter_tools:
            # Bind the openrouter tools directly to the call arguments
            return self.bind(tools=openrouter_tools, **kwargs)

        return super().bind_tools(standard_tools, **kwargs)
