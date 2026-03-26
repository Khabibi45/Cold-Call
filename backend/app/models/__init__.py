# Import de tous les modeles pour que SQLAlchemy les detecte au create_all
from app.models.lead import Lead  # noqa: F401
from app.models.call import Call  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.scrape_job import ScrapeJob  # noqa: F401
