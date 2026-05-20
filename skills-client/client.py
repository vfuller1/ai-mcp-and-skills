"""
MCP Skills Client - demonstrates discovery and use of all three MCP primitives.

Commands:
  /tools               List available tools
  /resources           List available resources
  /resource <uri>      Read a specific resource
  /skills              List available prompts (skills)
  /skill <name>        Invoke a skill interactively
  quit                 Exit
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


class MCPSkillsClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.openai = OpenAI()
        self.tools_cache = []
        self.prompts_cache = []
        self.resources_cache = []

    async def connect_to_server(self, server_script_path: str):
        command = "python" if server_script_path.endswith(".py") else "node"
        server_params = StdioServerParameters(command=command, args=[server_script_path], env=None)
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()

        self.tools_cache = (await self.session.list_tools()).tools
        self.prompts_cache = (await self.session.list_prompts()).prompts
        self.resources_cache = (await self.session.list_resources()).resources

        print("\n--- Connected to MCP Server ---")
        print(f"  Tools:     {[t.name for t in self.tools_cache]}")
        print(f"  Resources: {[r.uri for r in self.resources_cache]}")
        print(f"  Skills:    {[p.name for p in self.prompts_cache]}")
        print("-------------------------------")

    def _mcp_tools_to_openai_format(self):
        return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}} for t in self.tools_cache]

    async def _run_openai_with_tools(self, messages):
        available_tools = self._mcp_tools_to_openai_format()
        final_text = []
        response = self.openai.chat.completions.create(model="gpt-4o", max_tokens=2000, messages=messages, tools=available_tools or None)
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
                tool_result_text = "".join(c.text for c in result.content if hasattr(c, "text"))
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result_text})
            response = self.openai.chat.completions.create(model="gpt-4o", max_tokens=2000, messages=messages, tools=available_tools)
            message = response.choices[0].message
            if message.content:
                final_text.append(message.content)
        return "\n".join(final_text)

    async def list_resources(self):
        print("\nAvailable Resources:")
        for r in self.resources_cache:
            print(f"  - {r.uri}\n    {r.description or ''}")

    async def read_resource(self, uri):
        result = await self.session.read_resource(uri)
        print(f"\nResource [{uri}]:")
        for c in result.contents:
            if hasattr(c, "text"): print(c.text)

    async def list_skills(self):
        print("\nAvailable Skills (Prompts):")
        for p in self.prompts_cache:
            args = [a.name for a in p.arguments] if p.arguments else []
            print(f"  - {p.name}\n    {p.description or ''}")
            if args: print(f"    Arguments: {', '.join(args)}")

    async def invoke_skill(self, skill_name):
        prompt_def = next((p for p in self.prompts_cache if p.name == skill_name), None)
        if not prompt_def:
            print(f"Skill '{skill_name}' not found.")
            return
        arguments = {}
        if prompt_def.arguments:
            print(f"\nSkill '{skill_name}' requires:")
            for arg in prompt_def.arguments:
                value = input(f"  {arg.name} ({'required' if arg.required else 'optional'}): ").strip()
                if value: arguments[arg.name] = value
        print(f"\nInvoking skill '{skill_name}'...")
        prompt_result = await self.session.get_prompt(skill_name, arguments)
        messages = []
        for msg in prompt_result.messages:
            content_text = msg.content.text if hasattr(msg.content, "text") else str(msg.content)
            messages.append({"role": msg.role, "content": content_text})
        resource_context = await self._gather_resource_context(messages)
        if resource_context:
            messages.insert(0, {"role": "system", "content": f"Reference data:\n\n{resource_context}"})
        print(f"\n{await self._run_openai_with_tools(messages)}")

    async def _gather_resource_context(self, messages):
        all_text = " ".join(m.get("content", "") for m in messages)
        texts = []
        for r in self.resources_cache:
            if str(r.uri) in all_text:
                try:
                    result = await self.session.read_resource(r.uri)
                    for c in result.contents:
                        if hasattr(c, "text"): texts.append(f"[Resource: {r.uri}]\n{c.text}")
                except Exception:
                    pass
        return "\n\n".join(texts)

    async def process_query(self, query):
        return await self._run_openai_with_tools([{"role": "user", "content": query}])

    async def chat_loop(self):
        print("\nMCP Skills Client Started!")
        print("Commands: /tools  /resources  /resource <uri>  /skills  /skill <name>  quit\n")
        while True:
            try:
                query = input("Query: ").strip()
                if not query: continue
                if query.lower() == "quit": break
                elif query == "/tools":
                    print("\nAvailable Tools:")
                    for t in self.tools_cache: print(f"  - {t.name}: {t.description}")
                elif query == "/resources": await self.list_resources()
                elif query.startswith("/resource "): await self.read_resource(query[10:].strip())
                elif query == "/skills": await self.list_skills()
                elif query.startswith("/skill "): await self.invoke_skill(query[7:].strip())
                elif query.startswith("/"): print("Unknown command.")
                else: print(f"\n{await self.process_query(query)}")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"\nError: {e}")

    async def cleanup(self):
        await self.exit_stack.aclose()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)
    client = MCPSkillsClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
