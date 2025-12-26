import logging
import sys
import json
import uuid
import time
import os
import platform
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, List, Any, Optional
from fastapi import FastAPI, Request, Depends, Header, HTTPException, Form
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from datetime import datetime, timedelta

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil not installed, system monitoring features will be limited. Run: pip install psutil")

from app.core.config import settings
from app.providers.perplexity_provider import PerplexityProvider

# [Modified] Set log level to DEBUG, format includes filename and line number
logger.remove()
logger.add(
    sys.stdout, 
    level="DEBUG", 
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

provider = PerplexityProvider()

# Simulated account data storage (should use database in production)
accounts_db: Dict[str, Dict[str, Any]] = {}
logs_db: List[Dict[str, Any]] = []
custom_models: List[Dict[str, Any]] = [
    {"id": "gpt-4", "name": "GPT-4", "provider": "openai", "is_custom": False},
    {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "provider": "openai", "is_custom": False},
    {"id": "claude-3-opus", "name": "Claude 3 Opus", "provider": "anthropic", "is_custom": False},
]

def load_accounts_from_sessions():
    """Load saved accounts from data/sessions/ directinto accounts_db"""
    sessions_dir = Path("data/sessions")
    if not sessions_dir.exists():
        logger.info("📁 Sessions directory not found, skipping account loading")
        return
    
    for session_file in sessions_dir.glob("*.json"):
        try:
            logger.debug(f"Processing session file: {session_file}")
            with open(session_file, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            account_name = session_data.get("account_name")
            if not account_name:
                logger.warning(f"⚠️ Session file missing account name: {session_file}")
                continue
            
            logger.info(f"📂 Found account: {account_name}")
            
            # Check if account with same name already exists (avoid duplicates)
            existing_account = None
            for acc_id, acc in accounts_db.items():
                if acc.get("name") == account_name:
                    existing_account = acc_id
                    break
            
            if existing_account:
                # Update existing record
                account_id = existing_account
                logger.debug(f"📝 Updating existing account: {account_name}")
            else:
                # Create new record
                account_id = str(uuid.uuid4())[:8]
                logger.info(f"📂 Loading account: {account_name} (session file: {session_file.name})")
            
            # Get Cookie file info - enhanced path handling
            cookie_file = session_data.get("cookie_file", "")
            cookie_count = 0
            cookie_file_path = None
            
            if cookie_file:
                # Try direct path
                cookie_file_path = Path(cookie_file)
                if not cookie_file_path.exists():
                    # Try relative to current working directory
                    cookie_file_path = Path.cwd() / cookie_file
                    if not cookie_file_path.exists():
                        # Try to get from directory_info
                        dir_info = session_data.get("directory_info", {})
                        cookie_json = dir_info.get("cookie_json", "")
                        if cookie_json:
                            cookie_file_path = Path(cookie_json)
                            if not cookie_file_path.exists():
                                cookie_file_path = Path.cwd() / cookie_json
                        else:
                            # Try to find in data/cookies/account_name/
                            candidate = Path("data/cookies") / account_name / "cookies.json"
                            if candidate.exists():
                                cookie_file_path = candidate
                
                if cookie_file_path and cookie_file_path.exists():
                    try:
                        with open(cookie_file_path, 'r', encoding='utf-8') as cf:
                            cookie_data = json.load(cf)
                        cookie_count = cookie_data.get("cookie_count", 0)
                        logger.debug(f"✅ Successfully read Cookie file: {cookie_file_path}, cookie_count: {cookie_count}")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to read Cookie file {cookie_file_path}: {e}")
                else:
                    logger.warning(f"⚠️ Cookie file does not exist: {cookie_file}, tried path: {cookie_file_path}")
            else:
                logger.warning(f"⚠️ cookie_file field not specified in session file")
            
            # Get directory info
            dir_info = session_data.get("directory_info", {})
            account_dir = dir_info.get("account_dir", f"data/cookies/{account_name}")
            cookie_json = dir_info.get("cookie_json", "")
            cookie_txt = dir_info.get("cookie_txt", "")
            
            # Create account record (structure consistent with Web UI additions)
            account_record = {
                "id": account_id,
                "name": account_name,
                "is_active": True,
                "token_source": session_data.get("source", "unknown"),
                "data_dir": account_dir,
                "token": "Locally saved Cookie",
                "expires_at": (datetime.now() + timedelta(days=30)).isoformat(),
                "total_calls": session_data.get("stats", {}).get("total_calls", 0),
                "discord_username": None,
                "created_at": datetime.fromtimestamp(session_data.get("created_at", time.time())).isoformat(),
                "cookie_count": cookie_count,
                "user_agent_preview": "",  # Can be obtained from Cookie file, but simplified
                "local_saved": True,
                "cookie_files": [cookie_json, cookie_txt]
            }
            accounts_db[account_id] = account_record
            logger.info(f"✅ Successfully loaded account: {account_name} (ID: {account_id}, Cookie count: {cookie_count})")
            
        except Exception as e:
            logger.error(f"❌ Failed to load session file {session_file}: {e}")
            import traceback
            traceback.print_exc()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} (Botasaurus Deep Debug Mode)...")
    logger.info("Initializing Botasaurus browser service...")
    try:
        # Load locally saved accounts first
        load_accounts_from_sessions()
        logger.info(f"📊 Loaded {len(accounts_db)} local accounts")
        
        # Then initialize Botasaurus
        await provider.solver.initialize_session()
    except Exception as e:
        logger.error(f"Initialization failed: {e}")
    yield
    logger.info("Service shutdown.")

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

async def verify_key(authorization: str = Header(None)):
    if settings.API_MASTER_KEY != "1":
        if not authorization or authorization.split(" ")[1] != settings.API_MASTER_KEY:
            raise HTTPException(403, "Invalid API Key")

# ==================== Original API ====================
@app.post("/v1/chat/completions", dependencies=[Depends(verify_key)])
async def chat(request: Request):
    try:
        data = await request.json()
        # [Added] Print client raw request
        logger.debug(f"Received client request: {data}")
        
        # Check if provider is ready
        if not hasattr(provider, 'solver'):
            raise HTTPException(503, "Service is initializing, please try again later or add account via Web UI")
        
        # Check if valid Cookie is available
        if not provider.solver.get_cookies():
            raise HTTPException(400, "No valid Cookie found, please add account or import Cookie via Web UI")
        
        return await provider.chat_completion(data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Request Error: {e}")
        raise HTTPException(500, f"Internal server error: {str(e)}")

@app.get("/v1/models")
async def models():
    return await provider.get_models()

# ==================== Conversation Management API ====================
@app.get("/api/conversations")
async def get_conversations():
    """Get conversation statistics"""
    stats = provider.conversation_manager.get_stats()
    return JSONResponse(content={
        "success": True,
        "stats": stats
    })

@app.post("/api/conversations/reset")
async def reset_conversation(request: Request):
    """Reset a specific conversation or all conversations"""
    try:
        data = await request.json()
        conversation_id = data.get("conversation_id", "default")
        
        await provider.conversation_manager.reset_conversation(conversation_id)
        
        return JSONResponse(content={
            "success": True,
            "message": f"✅ Conversation '{conversation_id}' has been reset"
        })
    except Exception as e:
        return JSONResponse(content={
            "success": False,
            "message": f"❌ Failed to reset conversation: {str(e)}"
        })

@app.post("/api/conversations/reset-all")
async def reset_all_conversations():
    """Reset all conversations"""
    try:
        # Get all conversation IDs
        stats = provider.conversation_manager.get_stats()
        conversation_ids = list(stats.get("conversations", {}).keys())
        
        for cid in conversation_ids:
            await provider.conversation_manager.reset_conversation(cid)
        
        return JSONResponse(content={
            "success": True,
            "message": f"✅ Reset {len(conversation_ids)} conversations"
        })
    except Exception as e:
        return JSONResponse(content={
            "success": False,
            "message": f"❌ Failed to reset conversations: {str(e)}"
        })

# ==================== Account Management API ====================
@app.get("/api/accounts")
async def get_accounts():
    """Get all accounts list"""
    accounts = list(accounts_db.values())
    active_count = sum(1 for acc in accounts if acc.get("is_active", False))
    inactive_count = len(accounts) - active_count
    return JSONResponse(content={
        "accounts": accounts,
        "active_count": active_count,
        "inactive_count": inactive_count,
        "total": len(accounts)
    })

@app.post("/api/account/login/start")
async def start_login(name: str = Form(...)):
    """Start real browser login (using Botasaurus)"""
    import asyncio
    
    account_id = str(uuid.uuid4())[:8]
    
    try:
        logger.info(f"🔄 Starting interactive login process, account: {name}")
        
        # Set timeout (5 minutes)
        try:
            result = await asyncio.wait_for(
                provider.solver.interactive_login(name),
                timeout=300  # 5 minutes
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Login timeout, account: {name}")
            return JSONResponse(content={
                "success": False,
                "message": "❌ Login timeout (5 minutes). Please check if browser window opened properly.",
                "account_id": account_id
            })
        
        if result.get("success"):
            # Use actual account directory
            account_dir = result.get("account_dir", f"data/cookies/{name}")
            
            # Create account record
            new_account = {
                "id": account_id,
                "name": name,
                "is_active": True,
                "token_source": "browser",
                "data_dir": account_dir,
                "token": "Real Token (saved locally)",
                "expires_at": (datetime.now() + timedelta(days=30)).isoformat(),
                "total_calls": 0,
                "discord_username": None,
                "created_at": datetime.now().isoformat(),
                "cookie_count": len(result.get("cookies", {})),
                "user_agent_preview": result.get("user_agent", "")[:30] + "...",
                "local_saved": result.get("local_saved", False),
                "cookie_files": [
                    f"{account_dir}/cookies.json",
                    f"{account_dir}/cookies.txt"
                ]
            }
            accounts_db[account_id] = new_account
            
            # Add log
            logs_db.append({
                "timestamp": datetime.now().isoformat(),
                "account_name": name,
                "model": "N/A",
                "duration": 0,
                "status": "SUCCESS",
                "note": f"Interactive login successful, data saved to: {account_dir}",
                "level": "info"
            })
            
            logger.info(f"✅ Interactive login successful, account: {name}, data directory: {account_dir}")
            return JSONResponse(content={
                "success": True,
                "message": f"✅ Login successful! Retrieved {result.get('cookie_count', 0)} Cookies and saved to local directory.",
                "account_id": account_id,
                "cookie_count": len(result.get("cookies", {})),
                "user_agent_preview": result.get("user_agent", "")[:50],
                "account_dir": account_dir,
                "local_saved": result.get("local_saved", False)
            })
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error(f"❌ Login failed, account: {name}, error: {error_msg}")
            return JSONResponse(content={
                "success": False,
                "message": f"❌ Login failed: {error_msg}",
                "account_id": account_id
            })
            
    except Exception as e:
        logger.error(f"❌ Login process exception, account: {name}, error: {e}")
        return JSONResponse(content={
            "success": False,
            "message": f"❌ Login process exception: {str(e)}",
            "account_id": account_id
        })

@app.post("/api/token/refresh/{account_id}")
async def refresh_token(account_id: str):
    """Refresh account Token (simulated)"""
    if account_id not in accounts_db:
        raise HTTPException(404, "Account not found")
    
    account = accounts_db[account_id]
    account["token"] = "RefreshToken_" + str(uuid.uuid4())[:8]
    account["expires_at"] = (datetime.now() + timedelta(days=30)).isoformat()
    
    return JSONResponse(content={
        "success": True,
        "message": "✅ Token refresh successful (simulated)"
    })

@app.get("/api/account/toggle/{account_id}")
async def toggle_account(account_id: str):
    """Enable/Disable account"""
    if account_id not in accounts_db:
        raise HTTPException(404, "Account not found")
    
    account = accounts_db[account_id]
    account["is_active"] = not account.get("is_active", True)
    
    return JSONResponse(content={
        "success": True,
        "message": "✅ Account status updated",
        "is_active": account["is_active"]
    })

@app.get("/api/account/delete/{account_id}")
async def delete_account(account_id: str):
    """Delete account"""
    if account_id not in accounts_db:
        raise HTTPException(404, "Account not found")
    
    del accounts_db[account_id]
    
    return JSONResponse(content={
        "success": True,
        "message": "✅ Account deleted"
    })

# ==================== Log Management API ====================
@app.get("/api/logs")
async def get_logs():
    """Get recent logs"""
    return JSONResponse(content={
        "logs": logs_db[-50:]  # Return last 50 entries
    })

@app.get("/api/logs/clear")
async def clear_logs_get():
    """Clear logs (GET method for backward compatibility)"""
    logs_db.clear()
    return JSONResponse(content={
        "success": True,
        "message": "✅ Logs cleared"
    })

@app.post("/api/logs/clear")
async def clear_logs_post():
    """Clear logs (POST method)"""
    logs_db.clear()
    return JSONResponse(content={
        "success": True,
        "message": "✅ Logs cleared"
    })

# ==================== Service Control API ====================
@app.post("/api/service/stop")
async def stop_service():
    """Stop service (simulated)"""
    return JSONResponse(content={
        "success": True,
        "message": "🛑 Service stop command sent (requires process management)"
    })

@app.post("/api/settings/preview-mode")
async def set_preview_mode(request: Request):
    """Set preview mode"""
    data = await request.json()
    enabled = data.get("enabled", False)
    return JSONResponse(content={
        "success": True,
        "message": f"✅ Preview mode {'enabled' if enabled else 'disabled'}"
    })

# ==================== Web UI ====================
@app.get("/", response_class=HTMLResponse)
async def ui():
    """Serve Web UI"""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/ui-data")
async def ui_data():
    """Provide data for UI (for frontend JavaScript calls)"""
    accounts = list(accounts_db.values())
    active_count = sum(1 for acc in accounts if acc.get("is_active", False))
    inactive_count = len(accounts) - active_count
    
    return JSONResponse(content={
        "accounts": accounts,
        "active_count": active_count,
        "inactive_count": inactive_count,
        "logs": logs_db[-10:],
        "api_url": f"http://127.0.0.1:{settings.NGINX_PORT}",
        "version": "3.0"
    })

# ==================== System Monitoring API ====================

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    status = {
        "status": "healthy",
        "service": "perplexity-2api",
        "version": "3.0",
        "timestamp": datetime.now().isoformat()
    }
    
    # Check basic service status
    try:
        # Check Botasaurus status
        botasaurus_ready = False
        if hasattr(provider, 'solver'):
            solver = provider.solver
            if hasattr(solver, 'cached_cookies'):
                botasaurus_ready = True
        
        status["botasaurus_ready"] = botasaurus_ready
        status["accounts_count"] = len(accounts_db)
        status["logs_count"] = len(logs_db)
        
        if not botasaurus_ready:
            status["warning"] = "Botasaurus not ready, please add account via Web UI or check initialization"
        
    except Exception as e:
        status["status"] = "degraded"
        status["error"] = str(e)
    
    return JSONResponse(content=status)

def get_directory_size(path: str) -> int:
    """Calculate directory size (bytes)"""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
            elif entry.is_dir():
                total += get_directory_size(entry.path)
    except (PermissionError, FileNotFoundError):
        pass
    return total

def format_file_size(size_bytes: int) -> str:
    """Format file size"""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(units) - 1:
        size_bytes /= 1024
        i += 1
    return f"{size_bytes:.1f} {units[i]}"

@app.get("/api/system/status")
async def get_system_status():
    """Get system status"""
    status = {
        "service_status": "running",
        "botasaurus_status": "initializing",
        "total_accounts": len(accounts_db),
        "active_accounts": sum(1 for acc in accounts_db.values() if acc.get("is_active", False)),
        "api_requests": len(logs_db) if logs_db else 0,
        "memory_usage": 30,  # Default value
        "timestamp": datetime.now().isoformat()
    }
    
    # Check Botasaurus status
    try:
        if hasattr(provider, 'solver') and hasattr(provider.solver, 'cached_cookies'):
            status["botasaurus_status"] = "initialized"
        else:
            status["botasaurus_status"] = "initializing"
    except:
        status["botasaurus_status"] = "failed"
    
    # Get memory usage (if psutil available)
    if HAS_PSUTIL:
        try:
            process = psutil.Process()
            memory_percent = process.memory_percent()
            status["memory_usage"] = round(memory_percent, 1)
        except:
            pass
    
    return JSONResponse(content=status)

@app.get("/api/system/info")
async def get_system_info():
    """Get system information"""
    import sys as sys_module
    
    info = {
        "python_version": f"{sys_module.version_info.major}.{sys_module.version_info.minor}.{sys_module.version_info.micro}",
        "host_name": platform.node(),
        "working_dir": os.getcwd(),
        "platform": platform.platform(),
        "uptime": "Just started",  # Simplified version
        "start_time": datetime.now().isoformat()
    }
    
    return JSONResponse(content=info)

# ==================== File Management API ====================

@app.get("/api/files/list")
async def list_files(path: str = ""):
    """List files in specified directory"""
    base_path = Path.cwd()
    if path:
        target_path = (base_path / path).resolve()
        # Security check: ensure path is within project directory
        if not str(target_path).startswith(str(base_path)):
            raise HTTPException(403, "Access to this path is forbidden")
    else:
        target_path = base_path
    
    files = []
    try:
        for entry in os.scandir(target_path):
            try:
                file_info = {
                    "name": entry.name,
                    "path": str(Path(entry.path).relative_to(base_path)),
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else 0,
                    "modified": entry.stat().st_mtime,
                    "permissions": oct(entry.stat().st_mode)[-3:]
                }
                
                # If directory, estimate size
                if entry.is_dir():
                    try:
                        dir_size = get_directory_size(entry.path)
                        file_info["size"] = dir_size
                    except:
                        pass
                
                files.append(file_info)
            except (PermissionError, FileNotFoundError):
                continue
        
        # Sort by type and name
        files.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
        
    except (PermissionError, FileNotFoundError) as e:
        raise HTTPException(404, f"Cannot access directory: {str(e)}")
    
    return JSONResponse(content={"files": files, "current_path": str(target_path.relative_to(base_path))})

@app.get("/api/files/storage")
async def get_storage_info():
    """Get storage space information"""
    base_path = Path.cwd()
    
    # Calculate various directory sizes
    project_dir_size = get_directory_size(str(base_path))
    
    # Account data directory (if exists)
    account_data_path = base_path / "data"
    account_data_size = get_directory_size(str(account_data_path)) if account_data_path.exists() else 0
    
    # Log directory
    log_files_path = base_path / "error_logs"
    log_files_size = get_directory_size(str(log_files_path)) if log_files_path.exists() else 0
    
    # Cache directory (output directory)
    cache_files_path = base_path / "output"
    cache_files_size = get_directory_size(str(cache_files_path)) if cache_files_path.exists() else 0
    
    # Calculate total disk usage (if psutil available)
    storage_usage = 25  # Default value
    if HAS_PSUTIL:
        try:
            disk_usage = psutil.disk_usage(str(base_path))
            storage_usage = (disk_usage.used / disk_usage.total) * 100
        except:
            pass
    
    return JSONResponse(content={
        "project_dir_size": project_dir_size,
        "account_data_size": account_data_size,
        "log_files_size": log_files_size,
        "cache_files_size": cache_files_size,
        "storage_usage": round(storage_usage, 1),
        "formatted": {
            "project_dir_size": format_file_size(project_dir_size),
            "account_data_size": format_file_size(account_data_size),
            "log_files_size": format_file_size(log_files_size),
            "cache_files_size": format_file_size(cache_files_size),
        }
    })

@app.post("/api/files/clean-cache")
async def clean_cache():
    """Clean cache files"""
    base_path = Path.cwd()
    cache_dirs = ["output", "__pycache__", ".pytest_cache"]
    deleted_count = 0
    total_freed = 0
    
    for cache_dir in cache_dirs:
        cache_path = base_path / cache_dir
        if cache_path.exists():
            try:
                if cache_path.is_dir():
                    dir_size = get_directory_size(str(cache_path))
                    shutil.rmtree(cache_path)
                    deleted_count += 1
                    total_freed += dir_size
                    logger.info(f"Deleted cache directory: {cache_dir}")
            except Exception as e:
                logger.error(f"Failed to delete cache directory {cache_dir}: {e}")
    
    # Delete individual cache files
    cache_patterns = ["*.pyc", "*.log", "*.tmp"]
    for pattern in cache_patterns:
        for file_path in base_path.rglob(pattern):
            try:
                if file_path.is_file():
                    file_size = file_path.stat().st_size
                    file_path.unlink()
                    deleted_count += 1
                    total_freed += file_size
            except Exception as e:
                pass
    
    return JSONResponse(content={
        "success": True,
        "message": f"✅ Cleaned {deleted_count} cache items, freed {format_file_size(total_freed)}",
        "deleted_count": deleted_count,
        "freed_bytes": total_freed
    })

@app.post("/api/files/delete")
async def delete_files(request: Request):
    """Delete specified files/directories"""
    data = await request.json()
    paths = data.get("paths", [])
    
    if not paths:
        raise HTTPException(400, "No paths specified for deletion")
    
    base_path = Path.cwd()
    deleted = []
    errors = []
    
    for rel_path in paths:
        try:
            target_path = (base_path / rel_path).resolve()
            # Security check
            if not str(target_path).startswith(str(base_path)):
                errors.append(f"Access forbidden: {rel_path}")
                continue
            
            if target_path.exists():
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
                deleted.append(rel_path)
                logger.info(f"Deleted: {rel_path}")
            else:
                errors.append(f"File not found: {rel_path}")
        except Exception as e:
            errors.append(f"Delete failed {rel_path}: {str(e)}")
    
    return JSONResponse(content={
        "success": len(errors) == 0,
        "message": f"Deleted {len(deleted)} items, {len(errors)} errors",
        "deleted": deleted,
        "errors": errors
    })

# ==================== Enhanced Log API ====================

@app.get("/api/logs/recent")
async def get_recent_logs(limit: int = 100):
    """Get recent logs (with filtering support)"""
    recent_logs = []
    
    # This can be extended to read logs from files or database
    # Currently using in-memory logs
    for log in logs_db[-limit:]:
        recent_logs.append({
            "timestamp": log.get("timestamp", ""),
            "level": log.get("level", "info"),
            "message": log.get("note", "") or log.get("status", ""),
            "account": log.get("account_name", ""),
            "model": log.get("model", "")
        })
    
    return JSONResponse(content={"logs": recent_logs})

@app.post("/api/accounts/refresh-all")
async def refresh_all_accounts():
    """Refresh all accounts (simulated)"""
    # In production, this would call provider to refresh all account Cookies
    logger.info("Starting to refresh all accounts...")
    
    # Simulate refresh process
    import asyncio
    await asyncio.sleep(2)
    
    return JSONResponse(content={
        "success": True,
        "message": "✅ Requested refresh for all accounts, will execute in background",
        "account_count": len(accounts_db)
    })

@app.post("/api/account/refresh/{account_id}")
async def refresh_account(account_id: str):
    """Refresh specified account"""
    if account_id not in accounts_db:
        raise HTTPException(404, "Account not found")
    
    # Simulate refresh
    account = accounts_db[account_id]
    account["token"] = "RefreshToken_" + str(uuid.uuid4())[:8]
    account["expires_at"] = (datetime.now() + timedelta(days=30)).isoformat()
    account["total_calls"] = account.get("total_calls", 0) + 1
    
    logs_db.append({
        "timestamp": datetime.now().isoformat(),
        "account_name": account["name"],
        "level": "info",
        "note": "Account Token refreshed",
        "status": "SUCCESS"
    })
    
    return JSONResponse(content={
        "success": True,
        "message": "✅ Account refresh successful",
        "account_id": account_id
    })

@app.post("/api/cookie/parse")
async def parse_cookie_string(request: Request):
    """Parse Cookie string and create account"""
    try:
        data = await request.json()
        text = data.get("text", "")
        account_name = data.get("account_name", "Imported Account")
        
        if not text:
            raise HTTPException(400, "Please enter text content to parse")
        
        # Call BrowserService to parse Cookie
        result = provider.solver.parse_cookie_string(text, account_name)
        
        if result.get("success"):
            # Create account record
            account_id = str(uuid.uuid4())[:8]
            account_dir = result.get("account_dir", f"data/cookies/{account_name}")
            
            new_account = {
                "id": account_id,
                "name": account_name,
                "is_active": True,
                "token_source": "cookie_import",
                "data_dir": account_dir,
                "token": "Cookie Import (saved locally)",
                "expires_at": (datetime.now() + timedelta(days=30)).isoformat(),
                "total_calls": 0,
                "discord_username": None,
                "created_at": datetime.now().isoformat(),
                "cookie_count": result.get("cookie_count", 0),
                "user_agent_preview": result.get("user_agent", "")[:30] + "...",
                "local_saved": result.get("local_saved", False),
                "cookie_files": [
                    f"{account_dir}/cookies.json",
                    f"{account_dir}/cookies.txt"
                ]
            }
            accounts_db[account_id] = new_account
            
            # Add log
            logs_db.append({
                "timestamp": datetime.now().isoformat(),
                "account_name": account_name,
                "model": "N/A",
                "duration": 0,
                "status": "SUCCESS",
                "note": f"Cookie import successful, data saved to: {account_dir}",
                "level": "info"
            })
            
            return JSONResponse(content={
                "success": True,
                "message": f"✅ Cookie import successful! Extracted {result.get('cookie_count', 0)} Cookies and saved to local directory.",
                "account_id": account_id,
                "cookie_count": result.get("cookie_count", 0),
                "user_agent_preview": result.get("user_agent", "")[:50],
                "account_dir": account_dir
            })
        else:
            return JSONResponse(content={
                "success": False,
                "message": f"❌ Parse failed: {result.get('error', 'Unknown error')}"
            })
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Cookie parse exception: {e}")
        return JSONResponse(content={
            "success": False,
            "message": f"❌ Parse exception: {str(e)}"
        })

# ==================== API Key Management ====================

@app.get("/api/settings/api-key")
async def get_api_key():
    """Get current API Key"""
    return JSONResponse(content={
        "api_key": settings.API_MASTER_KEY,
        "masked": "***" + settings.API_MASTER_KEY[-4:] if len(settings.API_MASTER_KEY) > 4 else "***"
    })

@app.post("/api/settings/api-key")
async def update_api_key(request: Request):
    """Update API Key (write to .env file)"""
    try:
        data = await request.json()
        new_key = data.get("api_key", "").strip()
        
        if not new_key:
            raise HTTPException(400, "API Key cannot be empty")
        
        # Update .env file
        env_path = ".env"
        if not os.path.exists(env_path):
            raise HTTPException(500, "Cannot find .env file")
        
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        updated = False
        new_lines = []
        for line in lines:
            if line.startswith("API_MASTER_KEY="):
                new_lines.append(f'API_MASTER_KEY="{new_key}"\n')
                updated = True
            else:
                new_lines.append(line)
        
        if not updated:
            new_lines.append(f'API_MASTER_KEY="{new_key}"\n')
        
        with open(env_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        # Update in-memory settings (optional, full effect may require restart)
        # settings.API_MASTER_KEY = new_key
        
        logger.info("API Key updated")
        
        return JSONResponse(content={
            "success": True,
            "message": "✅ API Key updated. Note: some features may require a service restart to take effect.",
            "masked": "***" + new_key[-4:] if len(new_key) > 4 else "***"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update API Key: {e}")
        raise HTTPException(500, f"Update failed: {str(e)}")

@app.get("/api/settings/export-config")
async def export_config():
    """Export current system configuration (JSON format)"""
    try:
        # Collect configuration information
        config = {
            "export_time": datetime.now().isoformat(),
            "version": "3.0",
            "api_key_masked": "***" + settings.API_MASTER_KEY[-4:] if len(settings.API_MASTER_KEY) > 4 else "***",
            "system_settings": {
                "app_name": settings.APP_NAME,
                "app_version": settings.APP_VERSION,
                "api_master_key_length": len(settings.API_MASTER_KEY),
                "default_model": settings.DEFAULT_MODEL,
                "target_url": settings.TARGET_URL,
                "api_url": settings.API_URL,
                "nginx_port": settings.NGINX_PORT
            },
            "accounts": list(accounts_db.values()),
            "custom_models": custom_models,
            "statistics": {
                "total_accounts": len(accounts_db),
                "active_accounts": sum(1 for acc in accounts_db.values() if acc.get("is_active", False)),
                "total_logs": len(logs_db),
                "custom_models_count": len(custom_models)
            },
            "data_directories": {
                "cookies": "data/cookies/",
                "sessions": "data/sessions/",
                "logs": "error_logs/",
                "output": "output/"
            }
        }
        
        return JSONResponse(content={
            "success": True,
            "message": "✅ Configuration exported successfully",
            "config": config,
            "download_filename": f"perplexity-config-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        })
        
    except Exception as e:
        logger.error(f"Failed to export configuration: {e}")
        raise HTTPException(500, f"Failed to export configuration: {str(e)}")


# ==================== Account Detail API ====================

@app.get("/api/account/details/{account_name}")
async def get_account_details(account_name: str):
    """Get detailed account information (paths, creation time, update time, call stats, etc.)"""
    try:
        # Check if session file exists
        session_file = f"data/sessions/{account_name}.json"
        if not os.path.exists(session_file):
            raise HTTPException(404, f"Account '{account_name}' does not exist or session file not found")
        
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
        
        # Check if Cookie file exists
        cookie_file = session_data.get("cookie_file")
        cookie_data = None
        if cookie_file and os.path.exists(cookie_file):
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookie_data = json.load(f)
        
        # Build response
        response = {
            "account_name": account_name,
            "session_data": session_data,
            "cookie_data": cookie_data,
            "directory_info": session_data.get("directory_info", {}),
            "stats": session_data.get("stats", {}),
            "auto_maintenance": session_data.get("auto_maintenance", {}),
            "exists": True
        }
        
        return JSONResponse(content=response)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get account details: {e}")
        raise HTTPException(500, f"Failed to get account details: {str(e)}")

@app.post("/api/account/verify/{account_name}")
async def verify_account_cookie(account_name: str):
    """Manually verify Cookie validity (open browser to check)"""
    try:
        # Check if provider is ready
        if not hasattr(provider, 'solver'):
            raise HTTPException(503, "Service not ready")
        
        # Call BrowserService to verify Cookie
        result = await provider.solver.verify_cookie(account_name, headless=False)
        
        if result.get("success"):
            # Add log
            logs_db.append({
                "timestamp": datetime.now().isoformat(),
                "account_name": account_name,
                "level": "info",
                "note": f"Cookie verification succeeded: {result.get('message', '')}",
                "status": "SUCCESS"
            })
            
            return JSONResponse(content={
                "success": True,
                "message": result.get("message", "✅ Cookie verification succeeded"),
                "account_name": account_name,
                "valid": result.get("valid", False),
                "cookie_count": result.get("cookie_count", 0),
                "verification_time": result.get("verification_time"),
                "details": result
            })
        else:
            # Add log
            logs_db.append({
                "timestamp": datetime.now().isoformat(),
                "account_name": account_name,
                "level": "warning",
                "note": f"Cookie verification failed: {result.get('error', '')}",
                "status": "FAILED"
            })
            
            return JSONResponse(content={
                "success": False,
                "message": result.get("error", "❌ Cookie verification failed"),
                "account_name": account_name,
                "valid": False,
                "details": result
            })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cookie verification failed: {e}")
        raise HTTPException(500, f"Verification failed: {str(e)}")

# ==================== Account Statistics and Maintenance API ====================

@app.get("/api/account/stats/{account_name}")
async def get_account_stats(account_name: str):
    """Get account call statistics"""
    try:
        # Check session file
        session_file = f"data/sessions/{account_name}.json"
        if not os.path.exists(session_file):
            raise HTTPException(404, f"Account '{account_name}' does not exist")
        
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)
        
        stats = session_data.get("stats", {})
        auto_maintenance = session_data.get("auto_maintenance", {})
        
        return JSONResponse(content={
            "success": True,
            "account_name": account_name,
            "stats": stats,
            "auto_maintenance": auto_maintenance,
            "summary": {
                "total_calls": stats.get("total_calls", 0),
                "success_calls": stats.get("success_calls", 0),
                "failed_calls": stats.get("failed_calls", 0),
                "success_rate": stats.get("success_calls", 0) / max(stats.get("total_calls", 1), 1) * 100,
                "consecutive_failures": stats.get("consecutive_failures", 0),
                "last_success": stats.get("last_success"),
                "last_failure": stats.get("last_failure")
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get account statistics: {e}")
        raise HTTPException(500, f"Failed to get statistics: {str(e)}")

@app.post("/api/account/maintenance/{account_name}")
async def trigger_account_maintenance(account_name: str):
    """Trigger automatic account maintenance (force refresh Cookie)"""
    try:
        # Check if provider is ready
        if not hasattr(provider, 'solver'):
            raise HTTPException(503, "Service not ready")
        
        # Here we could call browser_service.perform_auto_maintenance
        # For now, simulate maintenance process
        logger.info(f"🔄 Starting manual maintenance for account: {account_name}")
        
        # Simulate maintenance delay
        import asyncio
        await asyncio.sleep(2)
        
        # Add log
        logs_db.append({
            "timestamp": datetime.now().isoformat(),
            "account_name": account_name,
            "level": "info",
            "note": "Manual maintenance triggered successfully, Cookie refresh will run in background",
            "status": "MAINTENANCE_TRIGGERED"
        })
        
        return JSONResponse(content={
            "success": True,
            "message": "✅ Account maintenance triggered, Cookie will be refreshed in the background",
            "account_name": account_name,
            "maintenance_time": datetime.now().isoformat(),
            "note": "Actual maintenance requires browser_service to implement perform_auto_maintenance"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger maintenance: {e}")
        raise HTTPException(500, f"Failed to trigger maintenance: {str(e)}")

# ==================== Model Management API ====================

@app.get("/api/models")
async def get_models_list():
    """Get model list (including custom models)"""
    # Get preset models (from provider.get_models)
    preset_models_response = await provider.get_models()
    preset_models = preset_models_response.body if hasattr(preset_models_response, 'body') else preset_models_response
    
    # 如果响应是JSON字符串，解析它
    if isinstance(preset_models, (bytes, str)):
        try:
            if isinstance(preset_models, bytes):
                preset_models = preset_models.decode('utf-8')
            preset_models = json.loads(preset_models)
        except:
            preset_models = {"data": []}
    
    # 提取data数组
    preset_models_list = preset_models.get("data", []) if isinstance(preset_models, dict) else preset_models
    
    # 添加is_custom标记
    for model in preset_models_list:
        if isinstance(model, dict):
            model["is_custom"] = False
            model["can_delete"] = False
            model["can_rename"] = False
    
    # 合并自定义模型（添加is_custom标记）
    for custom_model in custom_models:
        if isinstance(custom_model, dict):
            custom_model["is_custom"] = True
            custom_model["can_delete"] = True
            custom_model["can_rename"] = True
    
    # 合并所有模型
    all_models = preset_models_list + custom_models
    
    return JSONResponse(content={
        "models": all_models,
        "total": len(all_models),
        "custom_count": len(custom_models),
        "preset_count": len(preset_models_list)
    })

@app.post("/api/models")
async def add_model(request: Request):
    """Add a new model"""
    try:
        data = await request.json()
        model_id = data.get("id", "").strip()
        model_name = data.get("name", "").strip()
        provider_name = data.get("provider", "custom").strip()
        
        if not model_id:
            raise HTTPException(400, "Model ID cannot be empty")
        
        if not model_name:
            model_name = model_id
        
        # Check if already exists
        for model in custom_models:
            if model.get("id") == model_id:
                raise HTTPException(400, f"Model ID '{model_id}' already exists")
        
        # Add new model
        new_model = {
            "id": model_id,
            "name": model_name,
            "provider": provider_name,
            "is_custom": True,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        custom_models.append(new_model)
        
        # Add log
        logs_db.append({
            "timestamp": datetime.now().isoformat(),
            "level": "info",
            "note": f"Added custom model: {model_name} ({model_id})"
        })
        
        return JSONResponse(content={
            "success": True,
            "message": f"✅ Model '{model_name}' added successfully",
            "model": new_model
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add model: {e}")
        raise HTTPException(500, f"Failed to add model: {str(e)}")

@app.put("/api/models/{model_id}")
async def update_model(model_id: str, request: Request):
    """Rename/update a model"""
    try:
        data = await request.json()
        new_name = data.get("name", "").strip()
        
        if not new_name:
            raise HTTPException(400, "New name cannot be empty")
        
        # Find model (only in custom models)
        model_index = -1
        for i, model in enumerate(custom_models):
            if model.get("id") == model_id:
                model_index = i
                break
        
        if model_index == -1:
            raise HTTPException(404, f"Model '{model_id}' not found or preset models cannot be modified")
        
        # Update model
        old_name = custom_models[model_index].get("name", model_id)
        custom_models[model_index]["name"] = new_name
        custom_models[model_index]["updated_at"] = datetime.now().isoformat()
        
        # Add log
        logs_db.append({
            "timestamp": datetime.now().isoformat(),
            "level": "info",
            "note": f"Renamed model: {old_name} -> {new_name} ({model_id})"
        })
        
        return JSONResponse(content={
            "success": True,
            "message": f"✅ Model renamed successfully: {old_name} -> {new_name}",
            "model": custom_models[model_index]
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update model: {e}")
        raise HTTPException(500, f"Failed to update model: {str(e)}")

@app.delete("/api/models/{model_id}")
async def delete_model(model_id: str):
    """Delete a model (custom models only)"""
    try:
        # Find model (only in custom models)
        model_index = -1
        deleted_model = None
        
        for i, model in enumerate(custom_models):
            if model.get("id") == model_id:
                model_index = i
                deleted_model = model
                break
        
        if model_index == -1:
            raise HTTPException(404, f"Model '{model_id}' not found or preset models cannot be deleted")
        
        # Delete model
        deleted = custom_models.pop(model_index)
        
        # Add log
        logs_db.append({
            "timestamp": datetime.now().isoformat(),
            "level": "info",
            "note": f"Deleted model: {deleted.get('name', model_id)} ({model_id})"
        })
        
        return JSONResponse(content={
            "success": True,
            "message": f"✅ Model '{deleted.get('name', model_id)}' deleted successfully",
            "model_id": model_id
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete model: {e}")
        raise HTTPException(500, f"Failed to delete model: {str(e)}")

# ==================== Folder Management API ====================

@app.get("/api/folders/error_logs")
async def get_error_logs():
    """Get contents of error_logs folder"""
    try:
        error_logs_path = Path("error_logs")
        if not error_logs_path.exists():
            return JSONResponse(content={
                "success": True,
                "folder": "error_logs",
                "exists": False,
                "files": [],
                "total_size": 0,
                "message": "error_logs folder does not exist"
            })
        
        files = []
        total_size = 0
        
        # Traverse error_logs folder
        for entry in os.scandir(error_logs_path):
            try:
                file_info = {
                    "name": entry.name,
                    "path": str(entry.path),
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else get_directory_size(entry.path),
                    "modified": entry.stat().st_mtime,
                    "permissions": oct(entry.stat().st_mode)[-3:],
                    "is_directory": entry.is_dir()
                }
                total_size += file_info["size"]
                files.append(file_info)
            except (PermissionError, FileNotFoundError):
                continue
        
        # Sort by modified time (newest first)
        files.sort(key=lambda x: x["modified"], reverse=True)
        
        return JSONResponse(content={
            "success": True,
            "folder": "error_logs",
            "exists": True,
            "files": files,
            "total_size": total_size,
            "file_count": len(files),
            "message": f"Found {len(files)} files/directories, total size: {format_file_size(total_size)}"
        })
        
    except Exception as e:
        logger.error(f"Failed to get error_logs: {e}")
        raise HTTPException(500, f"Failed to get error_logs: {str(e)}")

@app.get("/api/folders/output")
async def get_output_folder():
    """Get contents of output folder"""
    try:
        output_path = Path("output")
        if not output_path.exists():
            return JSONResponse(content={
                "success": True,
                "folder": "output",
                "exists": False,
                "files": [],
                "total_size": 0,
                "message": "output folder does not exist"
            })
        
        files = []
        total_size = 0
        
        # Traverse output folder
        for entry in os.scandir(output_path):
            try:
                file_info = {
                    "name": entry.name,
                    "path": str(entry.path),
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else get_directory_size(entry.path),
                    "modified": entry.stat().st_mtime,
                    "permissions": oct(entry.stat().st_mode)[-3:],
                    "is_directory": entry.is_dir()
                }
                total_size += file_info["size"]
                files.append(file_info)
            except (PermissionError, FileNotFoundError):
                continue
        
        # Sort by modified time (newest first)
        files.sort(key=lambda x: x["modified"], reverse=True)
        
        return JSONResponse(content={
            "success": True,
            "folder": "output",
            "exists": True,
            "files": files,
            "total_size": total_size,
            "file_count": len(files),
            "message": f"Found {len(files)} files/directories, total size: {format_file_size(total_size)}"
        })
        
    except Exception as e:
        logger.error(f"Failed to get output folder: {e}")
        raise HTTPException(500, f"Failed to get output folder: {str(e)}")

@app.delete("/api/folders/error_logs/{filename}")
async def delete_error_log_file(filename: str):
    """Delete a file or directory in error_logs"""
    try:
        # Security check: prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(400, "Invalid filename")
        
        target_path = Path("error_logs") / filename
        if not target_path.exists():
            raise HTTPException(404, f"File does not exist: {filename}")
        
        # Security check: ensure path is within error_logs directory
        if not str(target_path.resolve()).startswith(str(Path.cwd().resolve() / "error_logs")):
            raise HTTPException(403, "Access to this path is forbidden")
        
        # Delete file or directory
        if target_path.is_dir():
            shutil.rmtree(target_path)
            action = "directory"
        else:
            target_path.unlink()
            action = "file"
        
        # Add log
        logs_db.append({
            "timestamp": datetime.now().isoformat(),
            "level": "info",
            "note": f"Deleted error_logs {action}: {filename}",
            "status": "FILE_DELETED"
        })
        
        logger.info(f"✅ Deleted error_logs {action}: {filename}")
        
        return JSONResponse(content={
            "success": True,
            "message": f"✅ Deleted {action}: {filename}"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete error_logs file: {e}")
        raise HTTPException(500, f"Delete failed: {str(e)}")

@app.delete("/api/folders/output/{filename}")
async def delete_output_file(filename: str):
    """Delete a file or directory in output"""
    try:
        # Security check: prevent path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(400, "Invalid filename")
        
        target_path = Path("output") / filename
        if not target_path.exists():
            raise HTTPException(404, f"File does not exist: {filename}")
        
        # Security check: ensure path is within output directory
        if not str(target_path.resolve()).startswith(str(Path.cwd().resolve() / "output")):
            raise HTTPException(403, "Access to this path is forbidden")
        
        # Delete file or directory
        if target_path.is_dir():
            shutil.rmtree(target_path)
            action = "directory"
        else:
            target_path.unlink()
            action = "file"
        
        # Add log
        logs_db.append({
            "timestamp": datetime.now().isoformat(),
            "level": "info",
            "note": f"Deleted output {action}: {filename}",
            "status": "FILE_DELETED"
        })
        
        logger.info(f"✅ Deleted output {action}: {filename}")
        
        return JSONResponse(content={
            "success": True,
            "message": f"✅ Deleted {action}: {filename}"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete output file: {e}")
        raise HTTPException(500, f"Delete failed: {str(e)}")

# ==================== 实时日志 SSE 端点（可选）====================
# 如果需要真正的实时日志，可以实现SSE端点
# 但为了简化，目前使用轮询方式