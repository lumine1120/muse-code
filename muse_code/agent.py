import os
import json
from openai import AsyncOpenAI
from .ui import UI
from .tools import TOOLS, AVAILABLE_FUNCTIONS
from .prompt import SYSTEM_PROMPT

class Agent:
    def __init__(self, ui: UI):
        self.ui = ui
        # Configure OpenAI Compatible API
        api_key = os.getenv("OPENAI_API_KEY", "sk-da55231cfba049438b776410797e5032")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")
        
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    async def run(self, user_input: str):
        self.messages.append({"role": "user", "content": user_input})
        
        while True:
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=TOOLS,
                    tool_choice="auto"
                )
            except Exception as e:
                self.ui.print_error(f"API Error: {str(e)}")
                break
            
            choice = response.choices[0]
            message = choice.message
            
            # Store the message in history
            self.messages.append(message)
            
            if message.content:
                self.ui.print_agent_message(message.content)
                
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    func_name = tool_call.function.name
                    func_args_str = tool_call.function.arguments
                    self.ui.print_tool_call(func_name, func_args_str)
                    
                    try:
                        args = json.loads(func_args_str)
                        func = AVAILABLE_FUNCTIONS.get(func_name)
                        if func:
                            result = str(func(**args))
                        else:
                            result = f"Error: Tool {func_name} not found."
                    except Exception as e:
                        result = f"Error executing tool: {str(e)}"
                        
                    self.ui.print_tool_result(result)
                    
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": result
                    })
                # Loop continues to send tool results back to LLM
            else:
                # No tool calls, turn is complete
                break
