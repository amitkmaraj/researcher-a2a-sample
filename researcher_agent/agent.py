import json
import uuid
from typing import List
import httpx
from typing import Any
import asyncio
import os

from google.adk import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.tool_context import ToolContext
from remote_agent_connection import RemoteAgentConnections, TaskUpdateCallback
from a2a.client import A2ACardResolver

from a2a.types import (
    SendMessageResponse,
    SendMessageRequest,
    MessageSendParams,
    SendMessageSuccessResponse,
    Task,
    Part,
    AgentCard,
)

from dotenv import load_dotenv

load_dotenv()


def convert_part(part: Part, tool_context: ToolContext):
    # Currently only support text parts
    if part.type == "text":
        return part.text

    return f"Unknown type: {part.type}"


def convert_parts(parts: list[Part], tool_context: ToolContext):
    rval = []
    for p in parts:
        rval.append(convert_part(p, tool_context))
    return rval


def create_send_message_payload(
    text: str, task_id: str | None = None, context_id: str | None = None
) -> dict[str, Any]:
    """Helper function to create the payload for sending a task."""
    payload: dict[str, Any] = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        },
    }

    if task_id:
        payload["message"]["taskId"] = task_id

    if context_id:
        payload["message"]["contextId"] = context_id
    return payload


class RoutingAgent:
    """The Routing agent.

    This is the agent responsible for choosing which remote seller agents to send
    tasks to and coordinate their work.
    """

    # __init__ becomes synchronous and simple
    def __init__(
        self,
        task_callback: TaskUpdateCallback | None = None,
    ):
        self.task_callback = task_callback
        self.remote_agent_connections: dict[str, RemoteAgentConnections] = {}
        self.cards: dict[str, AgentCard] = {}
        self.agents: str = ""

    # Asynchronous part of initialization
    async def _async_init_components(self, remote_agent_addresses: List[str]):
        # Use a single httpx.AsyncClient for all card resolutions for efficiency
        async with httpx.AsyncClient(timeout=30) as client:
            for address in remote_agent_addresses:
                card_resolver = A2ACardResolver(client, address) # Constructor is sync
                try:
                    card = await card_resolver.get_agent_card() # get_agent_card is async
                    remote_connection = RemoteAgentConnections(
                        agent_card=card, agent_url=address
                    )
                    self.remote_agent_connections[card.name] = remote_connection
                    self.cards[card.name] = card
                except httpx.ConnectError as e:
                    print(f"ERROR: Failed to get agent card from {address}: {e}")
                except Exception as e: # Catch other potential errors
                    print(f"ERROR: Failed to initialize connection for {address}: {e}")
        
        # Populate self.agents using the logic from original __init__ (via list_remote_agents)
        agent_info = []
        for agent_detail_dict in self.list_remote_agents(): 
            agent_info.append(json.dumps(agent_detail_dict))
        self.agents = "\n".join(agent_info)

    # Class method to create and asynchronously initialize an instance
    @classmethod
    async def create(
        cls,
        remote_agent_addresses: List[str],
        task_callback: TaskUpdateCallback | None = None,
    ):
        instance = cls(task_callback)
        await instance._async_init_components(remote_agent_addresses)
        return instance

    def create_agent(self) -> Agent:
        return Agent(
            model="gemini-2.5-flash-preview-04-17",
            name="Routing_agent",
            instruction=self.root_instruction,
            before_model_callback=self.before_model_callback,
            description=(
                "This expert researcher that can learn about topics and create requests to the appropriate researcher remote agents to teach users new concepts."
            ),
            tools=[
                self.send_message,
            ],
        )

    def root_instruction(self, context: ReadonlyContext) -> str:
        current_agent = self.check_active_agent(context)
        return f"""
        You are an expert researcher that can learn about topics and create requests to the
        appropriate researcher remote agents. Your goal is to accept a topic from a user, route it to an agent that can research and learn about the topic.
        Then, you need to take all that information and feed it to another agent that can teach it. The final teachable response should be sent to the user.

        Execution:
        - For actionable tasks, you can use `send_task` to assign tasks to remote agents to perform.
        - Never ask user permission when you want to connect with remote agents. If you need to make connection with multiple remote agents, directly
            connect with them without asking user permission or asking user preference
        - Always show the detailed response information from the researcher agent and propagate it properly to the user.  
        - If the user already confirmed the related order in the past conversation history, you can confirm on behalf of the user

        Please rely on tools to address the request, and don't make up the response. If you are not sure, please ask the user for more details.
        Focus on the most recent parts of the conversation primarily.

        If there is an active agent, send the request to that agent with the update task tool.

        **Agent Roster:**
        
        * Available Agents: `{self.agents}`
        * Currently Active Seller Agent: `{current_agent["active_agent"]}`
                """

    def check_active_agent(self, context: ReadonlyContext):
        state = context.state
        if (
            "session_id" in state
            and "session_active" in state
            and state["session_active"]
            and "active_agent" in state
        ):
            return {"active_agent": f"{state['active_agent']}"}
        return {"active_agent": "None"}

    def before_model_callback(self, callback_context: CallbackContext, llm_request):
        state = callback_context.state
        if "session_active" not in state or not state["session_active"]:
            if "session_id" not in state:
                state["session_id"] = str(uuid.uuid4())
            state["session_active"] = True

    def list_remote_agents(self):
        """List the available remote agents you can use to delegate the task."""
        if not self.cards: 
            return []

        remote_agent_info = []
        for card in self.cards.values():
            print(f"Found agent card: {card.model_dump(exclude_none=True)}")
            print("=" * 100)
            remote_agent_info.append(
                {"name": card.name, "description": card.description}
            )
        return remote_agent_info

    
    async def send_message(
        self, agent_name: str, task: str, tool_context: ToolContext
    ):
        """Sends a task to remote seller agent

        This will send a message to the remote agent named agent_name.

        Args:
            agent_name: The name of the agent to send the task to.
            task: The comprehensive conversation context summary
                and goal to be achieved regarding user inquiry and purchase request.
            tool_context: The tool context this method runs in.

        Yields:
            A dictionary of JSON data.
        """
        if agent_name not in self.remote_agent_connections:
            raise ValueError(f"Agent {agent_name} not found")
        state = tool_context.state
        state["active_agent"] = agent_name
        print("state", state)
        client = self.remote_agent_connections[agent_name]

        if not client:
            raise ValueError(f"Client not available for {agent_name}")
        if "task_id" in state:
            taskId = state["task_id"]

        else:
            taskId = str(uuid.uuid4())
        task_id = taskId
        sessionId = state["session_id"]
        if "context_id" in state:
            context_id = state["context_id"]
        else:
            context_id = str(uuid.uuid4())

        messageId = ""
        metadata = {}
        if "input_message_metadata" in state:
            metadata.update(**state["input_message_metadata"])
            if "message_id" in state["input_message_metadata"]:
                messageId = state["input_message_metadata"]["message_id"]
        if not messageId:
            messageId = str(uuid.uuid4())

        payload = {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": task}], # Use the 'task' argument here
                "messageId": messageId,
            },
        }

        if task_id:
            payload["message"]["taskId"] = task_id

        if context_id:
            payload["message"]["contextId"] = context_id
        
        message_request = SendMessageRequest(
            id=messageId, params=MessageSendParams.model_validate(payload)
        )
        send_response: SendMessageResponse = await client.send_message( message_request= message_request)
        print("send_response", send_response)

        if not isinstance(send_response.root, SendMessageSuccessResponse):
            print("received non-success response. Aborting get task ")
            return

        if not isinstance(send_response.root.result, Task):
            print("received non-task response. Aborting get task ")
            return

        response = send_response
        if hasattr(response, "root"):
            content = response.root.model_dump_json(exclude_none=True)
        else:
            content = response.model_dump(mode="json", exclude_none=True)

        resp = []
        json_content = json.loads(content)
        print(json_content)
        if json_content.get("result") and json_content["result"].get("artifacts"):
            for artifact in json_content["result"]["artifacts"]:
                if artifact.get("parts"):
                    resp.extend(artifact["parts"])
        return resp


def _get_initialized_routing_agent_sync():
    """Synchronously creates and initializes the RoutingAgent."""
    async def _async_main():
        routing_agent_instance = await RoutingAgent.create(
            remote_agent_addresses=[
                os.getenv("SCHOLAR_AGENT_URL", "http://localhost:10000"),
                os.getenv("TEACHER_AGENT_URL", "http://localhost:10003"),
            ]
        )
        return routing_agent_instance.create_agent()

    try:
        return asyncio.run(_async_main())
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            print(f"Warning: Could not initialize RoutingAgent with asyncio.run(): {e}. "
                  "This can happen if an event loop is already running (e.g., in Jupyter). "
                  "Consider initializing RoutingAgent within an async function in your application.")
        raise


root_agent = _get_initialized_routing_agent_sync()