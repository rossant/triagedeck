from fastapi_server.db import ensure_dev_seed_users, init_db


def main() -> None:
    init_db()
    ensure_dev_seed_users()


if __name__ == "__main__":
    main()
