from google.adk.agents import LlmAgent

def create_agent() -> LlmAgent:
    """Constructs the ADK agent."""
    return LlmAgent(
        model="gemini-2.5-flash-preview-04-17",
        name="teacher_agent",
        description="An agent that can help summarize concepts",
        instruction=f"""You are a teacher. Provide a summarization and examples of the provided research.""",
        tools=[],
    )