"""Cliente Prisma único, compartilhado por toda a aplicação."""
from __future__ import annotations

from prisma import Prisma

db = Prisma(auto_register=True)
