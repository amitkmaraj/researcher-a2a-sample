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

from typing import Callable, Any
import uuid

import httpx

# from a2a.client import A2AClient
from a2a.types import (
    SendMessageResponse,
    SendMessageRequest,
    AgentCard,
    Task,
    TaskStatusUpdateEvent,
    TaskArtifactUpdateEvent,
)
from a2a_client.client import A2AClient
from dotenv import load_dotenv
import os
import json

load_dotenv()

TaskCallbackArg = Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent
TaskUpdateCallback = Callable[[TaskCallbackArg, AgentCard], Task]

KNOWN_AUTH = {
    "scholar_agent": os.getenv("SCHOLAR_AGENT_AUTH", "api_key"),
    "teacher_agent": os.getenv("TEACHER_AGENT_AUTH", "api_key"),
}

class RemoteAgentConnections:
    """A class to hold the connections to the remote agents."""

    def __init__(self, agent_card: AgentCard, agent_url: str, auth: bool = True):
        print(f"agent_card: {agent_card}")
        print(f"agent_url: {agent_url}")

        auth = KNOWN_AUTH.get(agent_card.name, None)
        if auth:
            self.agent_client = A2AClient(agent_card, auth=auth, agent_url=agent_url)
        else:
            self.agent_client = A2AClient(agent_card, agent_url=agent_url)
        self.card = agent_card

        self.conversation_name = None
        self.conversation = None
        self.pending_tasks = set()

    def get_agent(self) -> AgentCard:
        return self.card

    async def send_message(self, message_request: SendMessageRequest) -> SendMessageResponse:
        return  await self.agent_client.send_message(message_request)

