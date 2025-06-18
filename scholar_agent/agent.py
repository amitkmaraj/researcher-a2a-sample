"""
Copyright 2025 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from langchain_google_vertexai import ChatVertexAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from typing import Literal
from pydantic import BaseModel
import uuid
from dotenv import load_dotenv
import os

load_dotenv()

memory = MemorySaver()


class ResponseFormat(BaseModel):
    """Respond to the user in this format."""

    status: Literal["in_progress", "completed", "error"] = "in_progress"
    message: str



class ScholarAgent:
    SYSTEM_INSTRUCTION = """
# INSTRUCTIONS

You are a scholar. Provide in-depth answers about the topic provided by the user.
"""
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        self.model = ChatVertexAI(
            model="gemini-2.0-flash",
            location=os.getenv("GOOGLE_CLOUD_LOCATION"),
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        )
        self.tools = []
        self.graph = create_react_agent(
            self.model,
            tools=self.tools,
            checkpointer=memory,
            prompt=self.SYSTEM_INSTRUCTION,
            response_format=ResponseFormat,
        )

    def invoke(self, query, sessionId) -> str:
        config = {"configurable": {"thread_id": sessionId}}
        self.graph.invoke({"messages": [("user", query)]}, config)
        return self.get_agent_response(config)

    def get_agent_response(self, config):
        current_state = self.graph.get_state(config)
        structured_response = current_state.values.get("structured_response")
        if structured_response and isinstance(structured_response, ResponseFormat):
            if structured_response.status == "in_progress":
                return {
                    "is_task_complete": False,
                    "content": structured_response.message,
                }
            elif structured_response.status == "error":
                return {
                    "is_task_complete": False,
                    "content": structured_response.message,
                }
            elif structured_response.status == "completed":
                return {
                    "is_task_complete": True,
                    "content": structured_response.message,
                }

        return {
            "is_task_complete": False,
            "content": "We are unable to process your request at the moment. Please try again.",
        }