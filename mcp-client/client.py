"""
Basic MCP Client - connects to an MCP server and lets you
ask free-form questions. The LLM uses MCP tools automatically.

Usage:
    python client.py <path_to_server_script>

Commands:
    Any text   Ask a question (LLM uses tools automatically)
    quit       Exit
"""

import asyncio
import json
import sys
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.openai = OpenAI()
        self.tools = []

    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server and discover its tools."""
        command = "python" if server_script_path.endswith(".py") else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path],
            env=None,
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

        tools_resp = await self.session.list_tools()
        self.tools = tools_resp.tools

        print(f"\nConnected to server with tools: {[t.name for t in self.tools]}")

    def _tools_to_openai_format(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.inputSchema,
                },
            }
            for t in self.tools
        ]

    async def process_query(self, query: str) -> str:
        """Send a query to OpenAI, handle any tool calls, return the final answer."""
        messages = [{"role": "user", "content": query}]
        available_tools = self._tools_to_openai_format()

        response = self.openai.chat.completions.create(
            model="gpt-4o",
            max_tokens=2000,
            messages=messages,
            tools=available_tools if available_tools else None,
        )

        final_text = []
        message = response.choices[0].message
        if message.content:
            final_text.append(message.content)

        while message.tool_calls:
            messages.append(message)

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                print(f"  -> Calling tool: {tool_name}({tool_args})")
                result = await self.session.call_tool(tool_name, tool_args)

                tool_result_text = "".join(
                    c.text for c in result.content if hasattr(c, "text")
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_text,
                })

            response = self.openai.chat.completions.create(
                model="gpt-4o",
                max_tokens=2000,
                messages=messages,
                tools=available_tools,
            )
            message = response.choices[0].message
            if message.content:
                final_text.append(message.content)

        return "\n".join(final_text)

    async def chat_loop(self):
        """Interactive chat loop."""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.\n")

        while True:
            try:
                query = input("Query: ").strip()
                if not query:
                    continue
                if query.lower() == "quit":
                    break
                response = await self.process_query(query)
                print(f"\n{response}\n")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}\n")

    async def cleanup(self):
        await self.exit_stack.aclose()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
