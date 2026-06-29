"""Identity service — auth, tenancy, entitlements & RBAC (REQ-077..084).

The multi-tenant control plane: platform owner over tenants; tenant-admins and
users within. Passwords are PBKDF2-hashed; sessions are opaque tokens; a plan +
per-tenant overrides decide each tenant's effective feature entitlements. Ported
from the monolith ``auth`` / ``entitlements`` / ``rbac`` modules.
"""
