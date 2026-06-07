import sys
import asyncio
from .ui import UI
from .agent import Agent

async def main_loop():
    ui = UI()
    ui.print_welcome()
    
    agent = Agent(ui)
    
    while True:
        try:
            user_input = ui.get_user_input()
            if not user_input or user_input.lower() in ['exit', 'quit']:
                ui.print_system("Goodbye!")
                break
            
            await agent.run(user_input)
        except KeyboardInterrupt:
            ui.print_system("\nExiting...")
            break
        except Exception as e:
            ui.print_error(f"Error: {str(e)}")

def main():
    asyncio.run(main_loop())

if __name__ == "__main__":
    main()
