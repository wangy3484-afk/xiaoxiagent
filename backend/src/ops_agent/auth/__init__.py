"""Local authentication boundary for interchangeable identity providers."""

from ops_agent.auth.service import AuthenticatedSession, AuthService

__all__ = ["AuthService", "AuthenticatedSession"]
