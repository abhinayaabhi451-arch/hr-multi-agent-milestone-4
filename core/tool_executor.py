"""Shared tool-calling loop used by every agent (Milestone 2: Tool
Integration & Intelligent Action Execution).

Keeps each agent file simple: build the prompt (with chat history),
ask the model for a response, and if the model asks to call a tool
instead of answering directly, run that tool, feed the result back,
and let the model try again -- looping until it gives a final answer
or a step limit is hit (so a misbehaving tool call can't hang forever).
"""

from langchain_core.messages import ToolMessage
from core.llm_client import extract_text


def run_with_tools(llm_with_tools, prompt_template, tools, query, chat_history, max_steps=4):
    tool_map = {t.name: t for t in tools}

    messages = prompt_template.invoke(
        {"query": query, "chat_history": chat_history}
    ).to_messages()

    for _ in range(max_steps):
        ai_message = llm_with_tools.invoke(messages)
        messages.append(ai_message)

        tool_calls = getattr(ai_message, "tool_calls", None)
        if not tool_calls:
            return extract_text(ai_message.content)

        for call in tool_calls:
            tool_fn = tool_map.get(call["name"])
            if tool_fn is None:
                result = f"Unknown tool requested: {call['name']}"
            else:
                try:
                    result = tool_fn.invoke(call["args"])
                except Exception as exc:
                    result = f"Tool error: {exc}"
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    return "I wasn't able to complete that after several tool attempts. Please rephrase or contact HR directly."
