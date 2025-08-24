from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import (
    Task,
    TaskState
)
from a2a.utils import (
    new_agent_text_message,
    new_task,
)
# from langGraph import graph
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.apps import A2AStarletteApplication
from langchain_core.messages import HumanMessage
import asyncio

skill1 = AgentSkill(
    id='relevancer-checker',
    name='Relevancer',
    description='Agent responsible for checking the topic queried by the user discussed within the course',
    tags=['relevancer-checker']
)
skill2 = AgentSkill(
    id='session-planner',
    name=' SPlanner',
    description='create a tutoring session plan for a specific topic',
    tags=['session-planner']
)
skill3 = AgentSkill(
    id=' exercise_generator',
    name=' Exerciser',
    description='genrate exercises for a specific topic',
    tags=['exercise_generator']
)
skill4 = AgentSkill(
    id='concept_clarifier',
    name='Conceptor',
    description='answer a question based on the material',
    tags=['concept_clarifier']
)
agent_card = AgentCard(
    name='tutoring agent',
    description='Agent that designs a tutoring session plan, generate exercises, and explain concepts ',
    url='http://localhost:9999/', # Agent will run here
    version='1.0.0',
    defaultInputModes=['text'], 
    defaultOutputModes=['text'],
    capabilities=AgentCapabilities(streaming=True), # Basic capabilities
    skills=[skill1, skill2, skill3, skill4] # Includes the skill defined above
)
class LanggraphAgentExecutor(AgentExecutor):
    def extract_content(self, message):
        """Extract content from either dict or message object"""
        if hasattr(message, 'content'):
            return message.content
        elif isinstance(message, dict) and 'content' in message:
            return message['content']
        else:
            return str(message)
    def __init__(self):
        self.agent = None
        self.connection_manager = None
        self.initialized = False
    
    async def initialize(self):
        if self.initialized:
            return
            
        # Import here to avoid circular imports
        from langGraph import MCPConnectionManager, main
        
        # Create a new connection manager inside the server process
        self.connection_manager = MCPConnectionManager()
        session = await self.connection_manager.initialize()
        
        # Create the graph with the active session
        self.agent = await main(session)
        self.initialized = True
            
    async def execute(
            self,
            context: RequestContext,
            event_queue: EventQueue,
    ) -> None:
        if not self.initialized:
            await self.initialize()

        query = context.get_user_input()
        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        
        try:
            # Create input with proper HumanMessage format
            input = {"messages": [HumanMessage(content=query)]}
            config = {'configurable': {'thread_id': task.context_id}}
            print(f"DEBUG: Starting execution for query: {query}")
            print(f"DEBUG: Task ID: {task.id}, Context ID: {task.context_id}")

            # Send initial status update
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(
                    "Processing your request...",
                    task.context_id,
                    task.id,
                ),
            )

            # Execute with timeout
            async with asyncio.timeout(150):
                print("DEBUG: Starting astrea m...")
                async for item in self.agent.astream(input, config, stream_mode='values'):
                    print(f"DEBUG: Received item: {type(item)} - {item}")
                    
                    # Check if queue is still active
                    if hasattr(event_queue, '_closed') and event_queue._closed:
                        print("Queue closed, terminating early")
                        break
                    
                    # Check for messages in the item
                    if 'messages' not in item or not item['messages']:
                        print("DEBUG: No messages in item, continuing...")
                        continue
                    
                    # Extract content safely
                    try:
                        content = self.extract_content(item['messages'][-1])
                        print(f"DEBUG: Extracted content: {content[:100]}...")
                    except Exception as content_error:
                        print(f"DEBUG: Error extracting content: {content_error}")
                        content = "Processing..."
                    
                    # Check if this is the final result
                    if item.get("next", None) == 'FINISH':
                        print("DEBUG: Received FINISH signal")
                        await updater.complete(message=new_agent_text_message(
                            content,
                            task.context_id,
                            task.id,
                        ))
                        print("DEBUG: Sent completion message")
                        break  # Important: exit after completion
                    else:
                        # Send progress update
                        await updater.update_status(
                            TaskState.working,
                            new_agent_text_message(
                                content,
                                task.context_id,
                                task.id,
                            ),
                        )
                        print("DEBUG: Sent status update")
                            
        except asyncio.TimeoutError:
            print("LangGraph execution timed out")
            try:
                await updater.complete(message=new_agent_text_message(
                    "Session planning timed out. Please try again with a simpler request.",
                    task.context_id,
                    task.id,
                ))
            except Exception as timeout_error:
                print(f"Could not send timeout message: {timeout_error}")
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Error in execute: {e}")
            print(f"Full traceback: {error_details}")
            
            # Try to send error message, but don't fail if updater is broken
            try:
                await updater.complete(message=new_agent_text_message(
                    f"An error occurred while processing your request: {str(e)}",
                    task.context_id,
                    task.id,
                ))
            except Exception as updater_error:
                print(f"Could not send error message via updater: {updater_error}")

    async def cancel(
            self, request: RequestContext, event_queue: EventQueue
    ) -> Task | None:
        print("Requested Cancel")


request_handler = DefaultRequestHandler(
            agent_executor=LanggraphAgentExecutor(),
            task_store=InMemoryTaskStore()
)

server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )

import uvicorn
host = "127.0.0.1"
port = 9999

uvicorn.run(server.build(), host=host, port=port)
