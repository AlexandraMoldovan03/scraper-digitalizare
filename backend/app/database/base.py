from sqlmodel import SQLModel

# Importăm modelele aici pentru ca Alembic să le vadă.
# Momentan fișierele sunt goale. Le vom completa în pașii următori.

from app.modules.organizations import models as organization_models  # noqa: F401
from app.modules.users import models as user_models  # noqa: F401
from app.modules.clients import models as client_models  # noqa: F401
from app.modules.market import models as market_models  # noqa: F401
from app.modules.properties import models as property_models  # noqa: F401
from app.modules.opportunities import models as opportunity_models  # noqa: F401
from app.modules.tasks import models as task_models  # noqa: F401
from app.modules.scraping import models as scraping_models  # noqa: F401


metadata = SQLModel.metadata
