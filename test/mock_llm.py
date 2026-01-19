import asyncio
import json
import time
import random
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    stream = body.get("stream", False)
    model = body.get("model", "mock-model")
    messages = body.get("messages", [])
    
    # Simple logic to decide whether to call tool
    should_call_tool = False
    last_message = messages[-1] if messages else {}
    if "weather" in str(last_message.get("content", "")).lower():
        should_call_tool = True

    if stream:
        async def event_generator():
            response_id = f"chatcmpl-{int(time.time())}"
            
            # Send role
            chunk_role = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(chunk_role)}\n\n"

            if should_call_tool:
                # Simulate tool call generation
                tool_call_id = f"call_{int(time.time())}"
                
                # First chunk with tool call id and name
                chunk_tool_start = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{
                        "index": 0, 
                        "delta": {
                            "tool_calls": [{
                                "index": 0,
                                "id": tool_call_id,
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": ""
                                }
                            }]
                        }, 
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(chunk_tool_start)}\n\n"
                
                # Stream arguments
                args_part1 = '{"loca'
                args_part2 = 'tion": "Bei'
                args_part3 = 'jing"}'
                
                for part in [args_part1, args_part2, args_part3]:
                    await asyncio.sleep(0.05)
                    chunk_args = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{
                            "index": 0, 
                            "delta": {
                                "tool_calls": [{
                                    "index": 0,
                                    "function": {"arguments": part}
                                }]
                            }, 
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_args)}\n\n"

                # Finish reason tool_calls
                chunk_finish_tool = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]
                }
                yield f"data: {json.dumps(chunk_finish_tool)}\n\n"

            else:
                # Normal text response
                content = "This is a mock response from the load test server. It simulates a streaming LLM response for Sage stress testing."
                tokens = content.split(" ")
                
                for token in tokens:
                    await asyncio.sleep(0.05)
                    chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": token + " "}, "finish_reason": None}]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                
                # Finish reason stop
                chunk_finish = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                }
                yield f"data: {json.dumps(chunk_finish)}\n\n"
            
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        # Non-streaming implementation (omitted for brevity as we focus on stream)
        return {}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
