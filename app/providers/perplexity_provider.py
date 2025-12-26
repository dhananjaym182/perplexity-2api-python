import json
import time
import uuid
import logging
import asyncio
from typing import Dict, Any, AsyncGenerator, Optional
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from loguru import logger
from collections import OrderedDict

# Use curl_cffi for TLS fingerprint impersonation to bypass Cloudflare
try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import httpx

from app.core.config import settings
from app.providers.base_provider import BaseProvider
from app.services.browser_service import BrowserService
from app.utils.sse_utils import create_sse_data, create_chat_completion_chunk, DONE_CHUNK


class ConversationManager:
    """
    Manages Perplexity conversation threads to maintain context across requests.
    Each conversation can handle up to max_turns before creating a new thread.
    """
    def __init__(self, max_turns: int = 50, max_conversations: int = 10):
        self.max_turns = max_turns
        self.max_conversations = max_conversations
        # conversation_id -> {"thread_uuid": str, "turn_count": int, "last_used": float, "backend_uuid": str}
        self.conversations: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.lock = asyncio.Lock()
    
    async def get_or_create_conversation(self, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get existing conversation or create a new one.
        Returns: {"thread_uuid": str, "backend_uuid": str, "is_new": bool, "turn_count": int}
        """
        async with self.lock:
            # If no conversation_id provided, use "default"
            if not conversation_id:
                conversation_id = "default"
            
            now = time.time()
            
            # Check if conversation exists and is still valid
            if conversation_id in self.conversations:
                conv = self.conversations[conversation_id]
                
                # Check if we've exceeded max turns
                if conv["turn_count"] >= self.max_turns:
                    logger.info(f"🔄 Conversation '{conversation_id}' reached {self.max_turns} turns, creating new thread")
                    # Create new thread for this conversation
                    conv["thread_uuid"] = str(uuid.uuid4())
                    conv["backend_uuid"] = None  # Will be set from response
                    conv["turn_count"] = 0
                    conv["last_used"] = now
                    return {
                        "thread_uuid": conv["thread_uuid"],
                        "backend_uuid": None,
                        "is_new": True,
                        "turn_count": 0
                    }
                
                # Update last used and increment turn count
                conv["turn_count"] += 1
                conv["last_used"] = now
                # Move to end (most recently used)
                self.conversations.move_to_end(conversation_id)
                
                return {
                    "thread_uuid": conv["thread_uuid"],
                    "backend_uuid": conv.get("backend_uuid"),
                    "is_new": False,
                    "turn_count": conv["turn_count"]
                }
            
            # Create new conversation
            # First, clean up old conversations if we're at max
            while len(self.conversations) >= self.max_conversations:
                oldest_id, _ = self.conversations.popitem(last=False)
                logger.debug(f"🗑️ Removed oldest conversation: {oldest_id}")
            
            thread_uuid = str(uuid.uuid4())
            self.conversations[conversation_id] = {
                "thread_uuid": thread_uuid,
                "backend_uuid": None,
                "turn_count": 1,
                "last_used": now
            }
            
            logger.info(f"✨ Created new conversation '{conversation_id}' with thread {thread_uuid[:8]}...")
            
            return {
                "thread_uuid": thread_uuid,
                "backend_uuid": None,
                "is_new": True,
                "turn_count": 1
            }
    
    async def update_backend_uuid(self, conversation_id: str, backend_uuid: str):
        """Update the backend_uuid after receiving response from Perplexity"""
        async with self.lock:
            if conversation_id in self.conversations:
                self.conversations[conversation_id]["backend_uuid"] = backend_uuid
                logger.debug(f"📝 Updated backend_uuid for '{conversation_id}': {backend_uuid[:8]}...")
    
    async def reset_conversation(self, conversation_id: str = "default"):
        """Force reset a conversation to start fresh"""
        async with self.lock:
            if conversation_id in self.conversations:
                del self.conversations[conversation_id]
                logger.info(f"🔄 Reset conversation: {conversation_id}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get conversation statistics"""
        return {
            "active_conversations": len(self.conversations),
            "max_conversations": self.max_conversations,
            "max_turns_per_conversation": self.max_turns,
            "conversations": {
                cid: {
                    "turn_count": conv["turn_count"],
                    "thread_uuid": conv["thread_uuid"][:8] + "...",
                    "has_backend_uuid": conv.get("backend_uuid") is not None
                }
                for cid, conv in self.conversations.items()
            }
        }


class PerplexityProvider(BaseProvider):
    def __init__(self):
        self.solver = BrowserService()
        # Conversation manager: 50 turns per conversation, max 10 active conversations
        self.conversation_manager = ConversationManager(max_turns=50, max_conversations=10)

    async def chat_completion(self, request_data: Dict[str, Any]) -> StreamingResponse:
        messages = request_data.get("messages", [])
        if not messages:
            raise HTTPException(status_code=400, detail="Messages cannot be empty")
        
        last_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if not last_msg:
            raise HTTPException(status_code=400, detail="No user message found")
        
        query = last_msg["content"]
        model = request_data.get("model", settings.DEFAULT_MODEL)
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        
        # Get conversation_id from request (optional, defaults to "default")
        # This allows clients to maintain separate conversations
        conversation_id = request_data.get("conversation_id", "default")
        
        # Get or create conversation thread
        conv_info = await self.conversation_manager.get_or_create_conversation(conversation_id)
        thread_uuid = conv_info["thread_uuid"]
        backend_uuid = conv_info["backend_uuid"]
        is_new_conversation = conv_info["is_new"]
        turn_count = conv_info["turn_count"]
        
        logger.info(f"📝 Conversation '{conversation_id}': turn {turn_count}, thread {thread_uuid[:8]}..., new={is_new_conversation}")

        # Build payload with conversation context
        payload = {
            "params": {
                "attachments": [],
                "language": "zh-CN",
                "timezone": "Asia/Shanghai",
                "search_focus": "internet",
                "sources": ["edgar", "social", "web", "scholar"],
                "frontend_uuid": thread_uuid,  # Use thread_uuid for conversation continuity
                "mode": "copilot",
                "model_preference": model,
                "is_related_query": not is_new_conversation,  # True if continuing conversation
                "is_sponsored": False,
                "prompt_source": "user",
                "query_source": "followup" if not is_new_conversation else "home",
                "is_incognito": False,
                "time_from_first_type": 1344.2,
                "local_search_enabled": False,
                "use_schematized_api": True,
                "send_back_text_in_streaming_api": False,
                "supported_block_use_cases": [
                  "answer_modes", "media_items", "knowledge_cards", "inline_entity_cards",
                  "place_widgets", "finance_widgets", "prediction_market_widgets", "sports_widgets",
                  "flight_status_widgets", "news_widgets", "shopping_widgets", "jobs_widgets",
                  "search_result_widgets", "clarification_responses", "inline_images", "inline_assets",
                  "placeholder_cards", "diff_blocks", "inline_knowledge_cards", "entity_group_v2",
                  "refinement_filters", "canvas_mode", "maps_preview", "answer_tabs",
                  "price_comparison_widgets", "preserve_latex"
                ],
                "client_coordinates": None,
                "mentions": [],
                "skip_search_enabled": True,
                "is_nav_suggestions_disabled": False,
                "always_search_override": False,
                "override_no_search": False,
                "should_ask_for_mcp_tool_confirmation": True,
                "supported_features": ["browser_agent_permission_banner"],
                "version": "2.18"
            },
            "query_str": query
        }
        
        # Add backend_uuid if we have one from previous response (for conversation continuity)
        if backend_uuid:
            payload["params"]["backend_uuid"] = backend_uuid
            logger.debug(f"Using backend_uuid: {backend_uuid[:8]}...")

        headers = self.solver.get_headers()
        headers["x-request-id"] = request_id
        cookies = self.solver.get_cookies()

        logger.info(f"=== Sending Request [{request_id}] ===")
        logger.debug(f"Query: {query[:100]}...")  # First 100 chars of query
        logger.debug(f"Cookies count: {len(cookies)}")
        logger.debug(f"Cookie keys: {list(cookies.keys())[:10]}...")  # First 10 keys
        logger.debug(f"cf_clearance present: {'cf_clearance' in cookies}")
        logger.debug(f"__cf_bm present: {'__cf_bm' in cookies}")
        logger.debug(f"Payload model_preference: {model}")

        async def stream_generator() -> AsyncGenerator[bytes, None]:
            # Use curl_cffi with Chrome impersonation to bypass Cloudflare TLS fingerprinting
            if HAS_CURL_CFFI:
                logger.debug("Using curl_cffi with Chrome impersonation")
                async with AsyncSession(impersonate="chrome") as session:
                    try:
                        # Build cookie string for curl_cffi
                        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
                        headers_with_cookie = headers.copy()
                        headers_with_cookie["Cookie"] = cookie_str
                        
                        response = await session.post(
                            settings.API_URL,
                            json=payload,
                            headers=headers_with_cookie,
                            timeout=300,
                            stream=True
                        )
                        
                        if response.status_code != 200:
                            error_preview = response.text[:500] if response.text else "No response body"
                            logger.error(f"Upstream error {response.status_code}: {error_preview}")
                            logger.debug(f"Request payload: {json.dumps(payload, ensure_ascii=False)[:500]}...")
                            logger.debug(f"Request headers: {headers_with_cookie}")
                            if response.status_code == 403:
                                logger.warning("⚠️ Cloudflare verification detected, Cookie may have expired. Please re-import Cookie via Web UI.")
                            elif response.status_code == 422:
                                logger.warning("⚠️ 422 error: Request format may be incorrect or query content was rejected.")
                            yield create_sse_data(create_chat_completion_chunk(request_id, model, f"[Error: Upstream {response.status_code} - Cookie may have expired, please re-import via Web UI]", "stop"))
                            yield DONE_CHUNK
                            return

                        last_full_text = ""
                        has_content = False
                        
                        # Process streaming response
                        buffer = ""
                        async for chunk in response.aiter_content():
                            if chunk:
                                buffer += chunk.decode('utf-8', errors='ignore')
                                while '\n' in buffer:
                                    line, buffer = buffer.split('\n', 1)
                                    line_str = line.strip()
                                    if not line_str or not line_str.startswith("data: "):
                                        continue
                                    
                                    json_str = line_str[6:].strip()
                                    if json_str == "[DONE]": continue
                                    
                                    try:
                                        data = json.loads(json_str)
                                        current_full_text = ""

                                        if "answer" in data:
                                            raw_answer = data["answer"]
                                            try:
                                                if isinstance(raw_answer, str) and raw_answer.strip().startswith("["):
                                                    steps = json.loads(raw_answer)
                                                    for step in steps:
                                                        step_type = step.get("step_type")
                                                        content = step.get("content", {})
                                                        
                                                        if step_type == "SEARCH_WEB":
                                                            queries = content.get("queries", [])
                                                            q_str = ", ".join([q["query"] for q in queries])
                                                            current_full_text += f"> 🔍 Searching: {q_str}\n\n"
                                                        
                                                        elif step_type == "SEARCH_RESULTS":
                                                            results = content.get("web_results", [])
                                                            if results:
                                                                current_full_text += f"> 📚 Found {len(results)} sources\n\n"

                                                        elif step_type == "FINAL":
                                                            final_answer_raw = content.get("answer")
                                                            if isinstance(final_answer_raw, str):
                                                                try:
                                                                    final_obj = json.loads(final_answer_raw)
                                                                    if "answer" in final_obj:
                                                                        current_full_text += final_obj["answer"]
                                                                except:
                                                                    current_full_text += final_answer_raw
                                                            else:
                                                                current_full_text += str(final_answer_raw)

                                                elif isinstance(raw_answer, str) and raw_answer.strip().startswith("{"):
                                                    inner_data = json.loads(raw_answer)
                                                    if "answer" in inner_data:
                                                        current_full_text = inner_data["answer"]
                                                else:
                                                    current_full_text = raw_answer
                                            except Exception as e:
                                                current_full_text = raw_answer

                                        elif "text" in data:
                                            raw_text = data["text"]
                                            try:
                                                if isinstance(raw_text, str) and raw_text.strip().startswith("["):
                                                    steps = json.loads(raw_text)
                                                    for step in steps:
                                                        step_type = step.get("step_type")
                                                        content = step.get("content", {})
                                                        if step_type == "FINAL":
                                                            final_answer_raw = content.get("answer")
                                                            if isinstance(final_answer_raw, str):
                                                                try:
                                                                    final_obj = json.loads(final_answer_raw)
                                                                    if "answer" in final_obj:
                                                                        current_full_text += final_obj["answer"]
                                                                except:
                                                                    current_full_text += final_answer_raw
                                                elif isinstance(raw_text, str) and raw_text.strip().startswith("{"):
                                                    inner_data = json.loads(raw_text)
                                                    if "answer" in inner_data:
                                                        current_full_text = inner_data["answer"]
                                                    elif "chunks" in inner_data:
                                                        current_full_text = "".join(inner_data["chunks"])
                                                else:
                                                    current_full_text = raw_text
                                            except:
                                                current_full_text = raw_text

                                        if current_full_text:
                                            if len(current_full_text) > len(last_full_text):
                                                delta_text = current_full_text[len(last_full_text):]
                                                last_full_text = current_full_text
                                                has_content = True
                                                
                                                chunk = create_chat_completion_chunk(request_id, model, delta_text)
                                                yield create_sse_data(chunk)

                                    except Exception as e:
                                        logger.warning(f"Parse failed: {e}")
                                        pass
                        
                        if not has_content:
                            yield create_sse_data(create_chat_completion_chunk(request_id, model, "[Warning: No content returned]", "stop"))

                        yield create_sse_data(create_chat_completion_chunk(request_id, model, "", "stop"))
                        yield DONE_CHUNK

                    except Exception as e:
                        logger.error(f"curl_cffi streaming request exception: {e}")
                        yield create_sse_data(create_chat_completion_chunk(request_id, model, f"[Error: {str(e)}]", "stop"))
                        yield DONE_CHUNK
            else:
                # Fallback to httpx (may get blocked by Cloudflare)
                logger.warning("curl_cffi not available, using httpx (may be blocked by Cloudflare)")
                import httpx
                client = httpx.AsyncClient(timeout=300, http2=True)
                try:
                    async with client.stream(
                        "POST",
                        settings.API_URL,
                        json=payload,
                        headers=headers,
                        cookies=cookies
                    ) as response:
                        
                        if response.status_code != 200:
                            error_text = await response.aread()
                            error_preview = error_text.decode('utf-8', errors='ignore')[:500]
                            logger.error(f"Upstream error {response.status_code}: {error_preview}")
                            if response.status_code == 403:
                                logger.warning("⚠️ Cloudflare verification detected, Cookie may have expired. Please re-import Cookie via Web UI.")
                            yield create_sse_data(create_chat_completion_chunk(request_id, model, f"[Error: Upstream {response.status_code} - Cookie may have expired, please re-import via Web UI]", "stop"))
                            yield DONE_CHUNK
                            return

                        last_full_text = ""
                        has_content = False
                        
                        async for line in response.aiter_lines():
                            line_str = line.strip()
                            if not line_str or not line_str.startswith("data: "):
                                continue
                            
                            json_str = line_str[6:].strip()
                            if json_str == "[DONE]": continue
                            
                            try:
                                data = json.loads(json_str)
                                current_full_text = ""

                                if "answer" in data:
                                    raw_answer = data["answer"]
                                    try:
                                        if isinstance(raw_answer, str) and raw_answer.strip().startswith("["):
                                            steps = json.loads(raw_answer)
                                            for step in steps:
                                                step_type = step.get("step_type")
                                                content = step.get("content", {})
                                                
                                                if step_type == "SEARCH_WEB":
                                                    queries = content.get("queries", [])
                                                    q_str = ", ".join([q["query"] for q in queries])
                                                    current_full_text += f"> 🔍 Searching: {q_str}\n\n"
                                                
                                                elif step_type == "SEARCH_RESULTS":
                                                    results = content.get("web_results", [])
                                                    if results:
                                                        current_full_text += f"> 📚 Found {len(results)} sources\n\n"

                                                elif step_type == "FINAL":
                                                    final_answer_raw = content.get("answer")
                                                    if isinstance(final_answer_raw, str):
                                                        try:
                                                            final_obj = json.loads(final_answer_raw)
                                                            if "answer" in final_obj:
                                                                current_full_text += final_obj["answer"]
                                                        except:
                                                            current_full_text += final_answer_raw
                                                    else:
                                                        current_full_text += str(final_answer_raw)

                                        elif isinstance(raw_answer, str) and raw_answer.strip().startswith("{"):
                                            inner_data = json.loads(raw_answer)
                                            if "answer" in inner_data:
                                                current_full_text = inner_data["answer"]
                                        else:
                                            current_full_text = raw_answer
                                    except Exception as e:
                                        current_full_text = raw_answer

                                elif "text" in data:
                                    raw_text = data["text"]
                                    try:
                                        if isinstance(raw_text, str) and raw_text.strip().startswith("["):
                                            steps = json.loads(raw_text)
                                            for step in steps:
                                                step_type = step.get("step_type")
                                                content = step.get("content", {})
                                                if step_type == "FINAL":
                                                    final_answer_raw = content.get("answer")
                                                    if isinstance(final_answer_raw, str):
                                                        try:
                                                            final_obj = json.loads(final_answer_raw)
                                                            if "answer" in final_obj:
                                                                current_full_text += final_obj["answer"]
                                                        except:
                                                            current_full_text += final_answer_raw
                                        elif isinstance(raw_text, str) and raw_text.strip().startswith("{"):
                                            inner_data = json.loads(raw_text)
                                            if "answer" in inner_data:
                                                current_full_text = inner_data["answer"]
                                            elif "chunks" in inner_data:
                                                current_full_text = "".join(inner_data["chunks"])
                                        else:
                                            current_full_text = raw_text
                                    except:
                                        current_full_text = raw_text

                                if current_full_text:
                                    if len(current_full_text) > len(last_full_text):
                                        delta_text = current_full_text[len(last_full_text):]
                                        last_full_text = current_full_text
                                        has_content = True
                                        
                                        chunk = create_chat_completion_chunk(request_id, model, delta_text)
                                        yield create_sse_data(chunk)

                            except Exception as e:
                                logger.warning(f"Parse failed: {e}")
                                pass
                        
                        if not has_content:
                            yield create_sse_data(create_chat_completion_chunk(request_id, model, "[Warning: No content returned]", "stop"))

                        yield create_sse_data(create_chat_completion_chunk(request_id, model, "", "stop"))
                        yield DONE_CHUNK

                except Exception as e:
                    logger.error(f"Streaming request exception: {e}")
                    yield create_sse_data(create_chat_completion_chunk(request_id, model, f"[Error: {str(e)}]", "stop"))
                    yield DONE_CHUNK
                finally:
                    await client.aclose()

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    async def get_models(self) -> JSONResponse:
        return JSONResponse(content={
            "object": "list",
            "data": [{"id": m, "object": "model", "created": int(time.time()), "owned_by": "perplexity"} for m in settings.MODELS]
        })