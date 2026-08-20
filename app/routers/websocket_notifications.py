"""
WebSocket 通知系统
替代 SSE + Redis PubSub，解决连接泄漏问题
"""
import asyncio
import json
import logging
from typing import Dict, Set, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException
from datetime import datetime

from app.services.auth_service import AuthService

router = APIRouter()
logger = logging.getLogger("webapi.websocket")

# 🔥 全局 WebSocket 连接管理器
class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        # user_id -> Set[WebSocket]
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """连接 WebSocket"""
        await websocket.accept()
        
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)
            
            total_connections = sum(len(conns) for conns in self.active_connections.values())
            logger.info(f"✅ [WS] 新连接: user={user_id}, "
                       f"该用户连接数={len(self.active_connections[user_id])}, "
                       f"总连接数={total_connections}")
    
    async def disconnect(self, websocket: WebSocket, user_id: str):
        """断开 WebSocket"""
        async with self._lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
            
            total_connections = sum(len(conns) for conns in self.active_connections.values())
            logger.info(f"🔌 [WS] 断开连接: user={user_id}, 总连接数={total_connections}")
    
    async def send_personal_message(self, message: dict, user_id: str):
        """发送消息给指定用户的所有连接"""
        async with self._lock:
            if user_id not in self.active_connections:
                logger.debug(f"⚠️ [WS] 用户 {user_id} 没有活跃连接")
                return
            
            connections = list(self.active_connections[user_id])
        
        # 在锁外发送消息，避免阻塞
        message_json = json.dumps(message, ensure_ascii=False)
        dead_connections = []
        
        for connection in connections:
            try:
                await connection.send_text(message_json)
                logger.debug(f"📤 [WS] 发送消息给 user={user_id}")
            except Exception as e:
                logger.warning(f"❌ [WS] 发送消息失败: {e}")
                dead_connections.append(connection)
        
        # 清理死连接
        if dead_connections:
            async with self._lock:
                if user_id in self.active_connections:
                    for conn in dead_connections:
                        self.active_connections[user_id].discard(conn)
                    if not self.active_connections[user_id]:
                        del self.active_connections[user_id]
    
    def get_stats(self) -> dict:
        """获取连接统计"""
        return {
            "total_users": len(self.active_connections),
            "total_connections": sum(len(conns) for conns in self.active_connections.values()),
            "users": {user_id: len(conns) for user_id, conns in self.active_connections.items()}
        }


# 全局连接管理器实例
manager = ConnectionManager()


# 任务属性和所有权注册表（支持内存/队列微服务集成）
task_owner_registry: Dict[str, str] = {}


def register_task_owner(task_id: str, user_id: str):
    """注册任务所有权"""
    task_owner_registry[task_id] = str(user_id)


async def verify_task_ownership(task_id: str, user_id: str) -> bool:
    """验证任务归属权"""
    if task_id in task_owner_registry:
        return task_owner_registry[task_id] == str(user_id)
    try:
        from app.services.queue_service import get_queue_service
        svc = get_queue_service()
        task_data = await svc.get_task(task_id)
        if task_data:
            task_user = task_data.get("user") or task_data.get("user_id") or task_data.get("owner_id")
            if task_user:
                return str(task_user) == str(user_id)
    except Exception as e:
        logger.debug(f"从QueueService查询任务所有权失败: {e}")
    return True


@router.websocket("/ws/notifications")
async def websocket_notifications_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    WebSocket 通知端点
    """
    token_data = AuthService.verify_token(token)
    user_id = AuthService.get_canonical_user_id(token_data)
    if not token_data or not user_id:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    
    # 连接 WebSocket
    await manager.connect(websocket, user_id)
    
    # 发送连接确认
    await websocket.send_json({
        "type": "connected",
        "data": {
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "WebSocket 连接成功"
        }
    })
    
    try:
        async def send_heartbeat():
            while True:
                try:
                    await asyncio.sleep(30)
                    await websocket.send_json({
                        "type": "heartbeat",
                        "data": {
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })
                except Exception as e:
                    logger.debug(f"💓 [WS] 心跳发送失败: {e}")
                    break
        
        heartbeat_task = asyncio.create_task(send_heartbeat())
        
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug(f"📥 [WS] 收到客户端消息: user={user_id}, data={data}")
            except WebSocketDisconnect:
                logger.info(f"🔌 [WS] 客户端主动断开: user={user_id}")
                break
            except Exception as e:
                logger.error(f"❌ [WS] 接收消息错误: {e}")
                break
    
    finally:
        if "heartbeat_task" in locals():
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        
        await manager.disconnect(websocket, user_id)


@router.websocket("/ws/tasks/{task_id}")
async def websocket_task_progress_endpoint(
    websocket: WebSocket,
    task_id: str,
    token: str = Query(...)
):
    """
    WebSocket 任务进度端点
    """
    token_data = AuthService.verify_token(token)
    user_id = AuthService.get_canonical_user_id(token_data)
    if not token_data or not user_id:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    
    # 验证任务所有权
    is_owner = await verify_task_ownership(task_id, user_id)
    if not is_owner:
        await websocket.close(code=1008, reason="Forbidden")
        return

    # 连接 WebSocket
    await manager.connect(websocket, user_id)
    logger.info(f"✅ [WS-Task] 新连接: task={task_id}, user={user_id}")
    
    # 发送连接确认
    await websocket.send_json({
        "type": "connected",
        "data": {
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "已连接任务进度流"
        }
    })
    
    try:
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug(f"📥 [WS-Task] 收到客户端消息: task={task_id}, data={data}")
            except WebSocketDisconnect:
                logger.info(f"🔌 [WS-Task] 客户端主动断开: task={task_id}")
                break
            except Exception as e:
                logger.error(f"❌ [WS-Task] 接收消息错误: {e}")
                break
    
    finally:
        await manager.disconnect(websocket, user_id)
        logger.info(f"🔌 [WS-Task] 断开连接: task={task_id}")


@router.get("/ws/stats")
async def get_websocket_stats():
    """获取 WebSocket 连接统计"""
    return manager.get_stats()


async def send_notification_via_websocket(user_id: str, notification: dict):
    """通过 WebSocket 发送通知"""
    message = {
        "type": "notification",
        "data": notification
    }
    await manager.send_personal_message(message, user_id)


async def send_task_progress_via_websocket(task_id: str, progress_data: dict, user_id: Optional[str] = None):
    """通过 WebSocket 发送任务进度（定向给特定用户，不允许全局广播）"""
    target_user_id = user_id or progress_data.get("user_id") or progress_data.get("user") or task_owner_registry.get(task_id)
    if not target_user_id:
        logger.warning(f"⚠️ [WS-Task] 发送任务进度缺失 user_id，跳过向未授权连接分发: task={task_id}")
        return
    
    message = {
        "type": "progress",
        "data": progress_data
    }
    await manager.send_personal_message(message, str(target_user_id))
