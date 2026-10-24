import warnings
warnings.filterwarnings("ignore", module="langchain_google_genai")

from agents.chatbot_agent import ChatbotAgent
from agents.onboarding_agent import OnboardingAgent
from agents.offboarding_agent import OffboardingAgent
from agents.maintenance_agent import MaintenanceAgent
from agents.coordinator_agent import CoordinatorAgent
from core.safe_call import safe_call


def build_agents():
    return {
        "chatbot": ChatbotAgent(),
        "onboarding": OnboardingAgent(),
        "offboarding": OffboardingAgent(),
        "maintenance": MaintenanceAgent(),
    }


def chat_with_agent(agent, name):
    """Stay in conversation with one agent until the user changes agent,
    goes back to the main menu, or quits."""
    print(f"\nYou're now chatting with the {name}. Keep typing queries.")
    print("Commands: 'c' = change agent, 'm' = main menu, 'q' = quit program")
    while True:
        query = input(f"\n[{name}] You: ").strip()
        cmd = query.lower()
        if cmd == "c":
            return "change"
        if cmd == "m":
            return "menu"
        if cmd == "q":
            return "quit"
        if not query:
            continue

        response = safe_call(agent.run, query)
        print(f"[{name}] {response}")


def manual_mode(agents):
    labels = {
        "1": ("chatbot", "Chatbot Agent"),
        "2": ("onboarding", "Onboarding Agent"),
        "3": ("offboarding", "Offboarding Agent"),
        "4": ("maintenance", "Maintenance Agent"),
    }
    while True:
        print("\nChoose an agent:")
        for key, (_, name) in labels.items():
            print(f"  {key}. {name}")
        print("  m. Back to main menu")

        choice = input("\nAgent number: ").strip().lower()
        if choice == "m":
            return "menu"
        if choice not in labels:
            print("Invalid choice, try again.")
            continue

        route, name = labels[choice]
        signal = chat_with_agent(agents[route], name)
        if signal == "change":
            continue  # back to the agent list, pick a different one
        if signal == "menu":
            return "menu"
        if signal == "quit":
            return "quit"


def auto_mode(coordinator):
    print("\nType your HR question below. The Coordinator Agent will route it")
    print("automatically to the right specialized agent each time.")
    print("(Mention your employee ID, e.g. E001, if your question needs one.")
    print(" Commands: 'm' = main menu, 'q' = quit program)")
    while True:
        query = input("\nYou: ").strip()
        cmd = query.lower()
        if cmd == "m":
            return "menu"
        if cmd == "q":
            return "quit"
        if not query:
            continue

        result = safe_call(coordinator.handle, query)
        if isinstance(result, tuple):
            route, response = result
            print(f"[Routed to: {route.title()} Agent]\n{response}")
        else:
            # safe_call returned its own error string instead of a (route, response) tuple
            print(result)


def main():
    print("=== HR Multi-Agent System (Milestones 1-3) ===")
    agents = build_agents()
    coordinator = CoordinatorAgent(agents)

    while True:
        print("\nMain Menu:")
        print("  1. Manual agent selection (you choose the agent)")
        print("  2. Auto-routing (Coordinator Agent decides)")
        print("  q. Quit")

        choice = input("\nChoice: ").strip().lower()
        if choice == "1":
            if manual_mode(agents) == "quit":
                break
        elif choice == "2":
            if auto_mode(coordinator) == "quit":
                break
        elif choice == "q":
            break
        else:
            print("Invalid choice, try again.")


if __name__ == "__main__":
    main()
