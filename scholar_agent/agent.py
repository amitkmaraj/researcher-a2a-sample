from google.adk.agents import LlmAgent

def create_agent() -> LlmAgent:
    """Constructs the ADK agent."""
    return LlmAgent(
        model="gemini-2.5-flash-preview-04-17",
        name="scholar_agent",
        description="An agent that can help research new topics",
        instruction=f"""You are a scholar. Provide in-depth answers about the topic provided by the user.""",
        tools=[],
    )