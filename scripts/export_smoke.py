from sqlalchemy import select

from fastapi_server.db import export_job, init_db, session_scope


def main() -> None:
    init_db()
    with session_scope() as session:
        count = session.execute(select(export_job.c.id)).all()
    print(f"export_jobs={len(count)}")


if __name__ == "__main__":
    main()
