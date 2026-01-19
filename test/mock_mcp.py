from mcp.server.fastmcp import FastMCP
import uvicorn

# Create FastMCP server
mcp = FastMCP("weather-server", host="0.0.0.0", port=9001)

@mcp.tool()
def get_weather(location: str) -> str:
    """Get the current weather in a given location"""
    return f"The weather in {location} is sunny."

if __name__ == "__main__":
    # sse_app() returns a Starlette app with /sse and /messages routes
    app = mcp.sse_app()
    uvicorn.run(app, host="0.0.0.0", port=9001)
