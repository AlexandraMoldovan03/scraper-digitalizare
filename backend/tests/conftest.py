"""
conftest.py — importă toate modelele SQLModel înainte de teste,
astfel că SQLModel.metadata e populat când engine_fixture apelează create_all.
"""
import os
import sys

# Setăm DATABASE_URL la SQLite înainte de orice import
# (session.py o citește la import-time; psycopg2 nu e disponibil în CI)
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ci.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")

# Adăugăm backend-ul în sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Importăm TOATE modelele pentru a le înregistra în SQLModel.metadata global,
# astfel că engine_fixture.create_all() le găsește deja înregistrate.
import app.modules.market.models          # noqa: F401 E402
import app.modules.scraping.models        # noqa: F401 E402
import app.modules.organizations.models   # noqa: F401 E402
import app.modules.users.models           # noqa: F401 E402
import app.modules.clients.models         # noqa: F401 E402
import app.modules.properties.models      # noqa: F401 E402
