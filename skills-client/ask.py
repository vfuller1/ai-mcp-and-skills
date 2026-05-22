"""One-shot query runner: python ask.py <question>"""
import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8")

from client import MCPSkillsClient

SERVER = str(__file__).replace("ask.py", "") + "../weather-skills/weather_server.py"

async def main():
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Are there any weather alerts in Texas?"
    client = MCPSkillsClient()
    try:
        await client.connect_to_server(SERVER)
        print(f"\nQuestion: {question}\n")
        answer = await client.process_query(question)
        print(answer)
    finally:
        await client.cleanup()

asyncio.run(main())
