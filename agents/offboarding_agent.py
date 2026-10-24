from core.llm_client import get_llm
from core.tool_executor import run_with_tools
from prompts.templates import OFFBOARDING_PROMPT
from tools.hr_tools import get_offboarding_checklist, revoke_access
from memory.short_term import ShortTermMemory


class OffboardingAgent:
    TOOLS = [get_offboarding_checklist, revoke_access]

    def __init__(self):
        self.llm = get_llm()
        self.llm_with_tools = self.llm.bind_tools(self.TOOLS)
        self.memory = ShortTermMemory()

    def run(self, query: str) -> str:
        response = run_with_tools(
            llm_with_tools=self.llm_with_tools,
            prompt_template=OFFBOARDING_PROMPT,
            tools=self.TOOLS,
            query=query,
            chat_history=self.memory.get_history(),
        )
        self.memory.add_user_message(query)
        self.memory.add_ai_message(response)
        return response
