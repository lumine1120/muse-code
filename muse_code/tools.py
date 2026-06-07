import json
import os
import subprocess

def execute_command(command: str) -> str:
    """Execute a shell command and return its output."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout
        if result.stderr:
            output += f"\nError: {result.stderr}"
        return output if output else "Command executed successfully with no output."
    except Exception as e:
        return str(e)

def read_file(filepath: str) -> str:
    """Read the content of a file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return str(e)

def write_file(filepath: str, content: str) -> str:
    """Write content to a file."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to {filepath}"
    except Exception as e:
        return str(e)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a shell command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "The absolute or relative path to the file."
                    }
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "The path to the file."
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write."
                    }
                },
                "required": ["filepath", "content"]
            }
        }
    }
]

AVAILABLE_FUNCTIONS = {
    "execute_command": execute_command,
    "read_file": read_file,
    "write_file": write_file
}
