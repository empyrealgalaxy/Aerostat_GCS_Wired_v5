import hashlib
import secrets
import time
from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, status
from config import config_manager

class AuthManager:
    def __init__(self):
        self.sessions = {}  # In production, use Redis or database
        self.session_timeout = 3600  # 1 hour in seconds

    def hash_password(self, password: str) -> str:
        """Hash password using SHA-256 (use bcrypt in production)"""
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash"""
        return self.hash_password(password) == hashed

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user credentials"""
        user_config = config_manager.get_user(username)
        if not user_config:
            return None
        
        # For demo purposes, we're using plain text passwords
        # In production, use proper password hashing
        if user_config.get("password") == password:
            return {
                "username": username,
                "role": user_config.get("role", "viewer"),
                "permissions": user_config.get("permissions", ["view"])
            }
        return None

    def create_session(self, user_data: Dict[str, Any]) -> str:
        """Create a new session"""
        session_id = secrets.token_urlsafe(32)
        self.sessions[session_id] = {
            **user_data,
            "created_at": time.time(),
            "last_activity": time.time()
        }
        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data"""
        if not session_id or session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        
        # Check if session has expired
        if time.time() - session["last_activity"] > self.session_timeout:
            self.destroy_session(session_id)
            return None
        
        # Update last activity
        session["last_activity"] = time.time()
        return session

    def destroy_session(self, session_id: str) -> bool:
        """Destroy a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        current_time = time.time()
        expired_sessions = []
        
        for session_id, session in self.sessions.items():
            if current_time - session["last_activity"] > self.session_timeout:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            self.destroy_session(session_id)

    def get_current_user(self, request: Request) -> Optional[Dict[str, Any]]:
        """Get current user from request session"""
        session_id = request.session.get("session_id")
        return self.get_session(session_id)

    def require_auth(self, request: Request) -> Dict[str, Any]:
        """Require authentication - raise exception if not authenticated"""
        user = self.get_current_user(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        return user

    def require_permission(self, request: Request, permission: str) -> Dict[str, Any]:
        """Require specific permission"""
        user = self.require_auth(request)
        if permission not in user.get("permissions", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required"
            )
        return user

    def require_admin(self, request: Request) -> Dict[str, Any]:
        """Require admin role"""
        user = self.require_auth(request)
        if user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required"
            )
        return user

    def has_permission(self, user: Dict[str, Any], permission: str) -> bool:
        """Check if user has specific permission"""
        return permission in user.get("permissions", [])

    def is_admin(self, user: Dict[str, Any]) -> bool:
        """Check if user is admin"""
        return user.get("role") == "admin"

    def is_operator(self, user: Dict[str, Any]) -> bool:
        """Check if user is operator or admin"""
        return user.get("role") in ["admin", "operator"]

    def login_user(self, request: Request, username: str, password: str) -> bool:
        """Login user and create session"""
        user_data = self.authenticate_user(username, password)
        if user_data:
            session_id = self.create_session(user_data)
            request.session["session_id"] = session_id
            request.session["user"] = username
            return True
        return False

    def logout_user(self, request: Request) -> bool:
        """Logout user and destroy session"""
        session_id = request.session.get("session_id")
        if session_id:
            self.destroy_session(session_id)
        request.session.clear()
        return True

    def get_user_info(self, request: Request) -> Dict[str, Any]:
        """Get current user information"""
        user = self.get_current_user(request)
        if user:
            return {
                "username": user["username"],
                "role": user["role"],
                "permissions": user["permissions"],
                "is_admin": self.is_admin(user),
                "is_operator": self.is_operator(user)
            }
        return {}

# Global auth instance
auth_manager = AuthManager()

# Dependency functions for FastAPI
def get_current_user(request: Request):
    return auth_manager.get_current_user(request)

def require_auth(request: Request):
    return auth_manager.require_auth(request)

def require_admin(request: Request):
    return auth_manager.require_admin(request)

def require_permission(permission: str):
    def _require_permission(request: Request):
        return auth_manager.require_permission(request, permission)
    return _require_permission
