import os
from pickle import TRUE
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import argparse
from pathlib import Path
from openai import OpenAI
from agents.agent.agent_controller import AgentController
from agents.professional_agents.code_agents import CodeAgent
from agents.tool.tool_manager import ToolManager
from agents.utils.logger import logger
import json
import streamlit as st
from typing import List, Dict
import uuid
def init_components(api_key: str, model_name: str, base_url: str, tools_folders: list):
    """Initialize tool manager and agent controller"""
    logger.info(f"Initializing components with model: {model_name}")
    sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    
    # Initialize tool manager
    tool_manager = ToolManager()
    for folder in tools_folders:
        logger.debug(f"Registering tools from directory: {folder}")
        tool_manager.register_tools_from_directory(folder)
    
    # Initialize model and controller
    logger.debug(f"Initializing model with base URL: {base_url}")
    model = OpenAI(api_key=api_key, base_url=base_url)
    model_config = {"model": model_name,"temperature": 0.2,"max_tokens":4096}
    controller = AgentController(model, model_config)
    logger.info("Components initialized successfully")

    tool_manager.register_tool(CodeAgent(model,model_config).to_tool())

    return tool_manager, controller

def convert_messages_for_show(messages):
    logger.debug(f"Converting {len(messages)} messages for display")
    new_messages = []
    for message in messages:
        new_message = {}
        new_message['message_id'] = message.get('message_id', str(uuid.uuid4()))
        if message['role'] == 'user':
            new_message['role'] = message['role']
        else:
            new_message['role'] = 'assistant'
        new_message['content'] = message['show_content'] if 'show_content' in message else message['content']
        if len(new_message['content'])>0:
            new_messages.append(new_message)
    return new_messages

def run_web_demo(tool_manager, controller):
    """Run Streamlit web interface with streaming"""
    logger.info("Starting Streamlit web demo")
    # Initialize conversation history in session state
    if "inference_conversation" not in st.session_state:
        logger.debug("Initializing inference_conversation in session state")
        st.session_state.inference_conversation = []
    
    st.title("Sage")
    st.sidebar.header("Settings")
    
    # Add multi-agent toggle
    use_multi_agent = st.sidebar.toggle('启用多智能体推理', value=True)
    use_deepthink = st.sidebar.toggle('启用深度思考', value=True)
    # Display available tools with descriptions
    logger.debug("Displaying available tools in sidebar")
    st.sidebar.subheader("Available Tools")
    for tool_info in tool_manager.list_tools_simplified():
        tool_name = tool_info['name']
        tool_description = tool_info['description']
        st.sidebar.markdown(f"- **{tool_name}**\n")
    
    if "conversation" not in st.session_state: 
        logger.debug("Initializing conversation in session state")
        st.session_state.conversation = []
    
    # Add clear history button
    if st.sidebar.button("Clear History"):
        logger.info("User cleared conversation history")
        st.session_state.conversation = []
        st.session_state.inference_conversation = []
        st.rerun()
    
    user_input = st.chat_input("Type your message here...")
    
    if user_input:

        # display history
        for msg in st.session_state.conversation:
            if msg['role'] == 'assistant':
                with st.chat_message("assistant"):
                    st.write(msg['content'])
            elif msg['role'] == 'user':
                with st.chat_message("user"):
                    st.write(msg['content'])

        logger.info(f"Received user input: {user_input[:30]}{'...' if len(user_input) > 30 else ''}")
        # Add user message to both conversations
        user_msg = {
            "role": "user",
            "content": user_input,
            "type": "normal",
            "message_id": str(uuid.uuid4())
        }
        st.session_state.conversation.append(user_msg)
        st.session_state.inference_conversation.append(user_msg)
        
        # Display user message immediately
        with st.chat_message("user"):
            st.write(user_input)
        
        # Track message streams by message_id
        message_streams = {}
        new_messages = []
        
        # Stream with real-time updates
        all_messages = st.session_state.inference_conversation.copy()
        new_messages = []
        current_stream_id = None
        current_stream = None
        
        logger.debug("Starting streaming response generation")
        for chunk in controller.run_stream(
            all_messages,
            tool_manager,
            session_id=None,
            deep_thinking=use_deepthink,
            summary=True,
            deep_research=use_multi_agent 
        ):
            new_messages.extend(chunk)
            
            # Get merged messages for display
            merged_temp = controller._merge_messages(all_messages.copy(), new_messages)
            display_messages = convert_messages_for_show(merged_temp)
            # Find the latest assistant message
            latest_assistant_msg = None
            for msg in reversed(display_messages):
                if msg['role']  in ['assistant','tool'] :
                    latest_assistant_msg = msg
                    break
            
            if latest_assistant_msg:
                msg_id = latest_assistant_msg.get('message_id', str(hash(latest_assistant_msg['content'])))
                
                # If this is a new message stream
                if msg_id != current_stream_id:
                    logger.debug(f"New message stream detected with ID: {msg_id}")
                    print('msg_id changed', msg_id,current_stream_id)
                    current_stream_id = msg_id
                    current_stream = st.chat_message('assistant').empty()
                
                # Clear and update the current stream
                # current_stream.empty()
                # print('latest_assistant_msg',latest_assistant_msg)
                current_stream.write(latest_assistant_msg['content'])
        
        # Final merge after streaming completes
        if new_messages:
            logger.debug(f"Stream completed, merging final {len(new_messages)} messages")
            all_messages = controller._merge_messages(all_messages, new_messages)
            st.session_state.inference_conversation = all_messages
            display_all_messages = convert_messages_for_show(all_messages)
            print(display_all_messages)
            st.session_state.conversation = display_all_messages
            logger.info("Web demo interaction completed")

def main():
    parser = argparse.ArgumentParser(description='Multi-Agent Interactive Chat')
    parser.add_argument('--api_key', required=True, help='OpenRouter API key')
    parser.add_argument('--model', default='mistralai/mistral-small-3.1-24b-instruct:free',
                      help='Model name (default: mistralai/mistral-small-3.1-24b-instruct:free)')
    parser.add_argument('--base_url', default='https://openrouter.ai/api/v1',
                      help='API base URL (default: https://openrouter.ai/api/v1)')
    parser.add_argument('--tools_folders',
                      nargs='+',
                      default=[],
                      help='Paths to tools directories (space separated, default: ../agents/tool)')    
    args = parser.parse_args()
    logger.info(f"Starting application with model: {args.model}")
    
    #  如果已经初始化了，就不重复初始化
    if 'tool_manager' not in st.session_state:
        logger.debug("Initializing components")
        tool_manager, controller = init_components(
            args.api_key,
            args.model,
            args.base_url,
            args.tools_folders
        )
        st.session_state.tool_manager = tool_manager
        st.session_state.controller = controller
    else:
        logger.debug("Components already initialized, skipping")
    run_web_demo(st.session_state.tool_manager, st.session_state.controller)

if __name__ == "__main__":
    main()
