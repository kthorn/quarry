from flask import Flask

from quarry.store.db import Database


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    if db_path is None:
        from quarry.config import settings

        db_path = settings.db_path

    db = Database(db_path)
    app.config["DB"] = db
    app.config["PER_PAGE"] = 20

    from quarry.ui.routes import bp

    app.register_blueprint(bp)

    return app
