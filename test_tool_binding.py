
import asyncio
from sagents.tool.tool_base import tool

class MyTools:
    def __init__(self, name):
        self.name = name

    @tool(description_i18n={"zh": "Test tool"})
    async def my_tool(self, arg: str) -> str:
        return f"{self.name}: {arg}"

async def main():
    tools = MyTools("instance1")
    bound_method = tools.my_tool
    
    print(f"Bound method: {bound_method}")
    print(f"Has __self__: {hasattr(bound_method, '__self__')}")
    if hasattr(bound_method, '__self__'):
        print(f"Self: {bound_method.__self__}")
        print(f"Self.name: {bound_method.__self__.name}")
    
    print(f"Is coroutine function: {asyncio.iscoroutinefunction(bound_method)}")
    
    # Simulate ToolManager execution logic
    if hasattr(bound_method, "__self__"):
        print("Executing as bound method...")
        res = await bound_method(arg="hello")
        print(f"Result: {res}")
    else:
        print("Executing as unbound method (ERROR simulation)...")

if __name__ == "__main__":
    asyncio.run(main())
