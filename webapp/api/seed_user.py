"""Interactively create one demo account without putting passwords in shell history."""

import argparse
from getpass import getpass

from .database import initialize_web_schema, transaction
from .security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--role", choices=("admin", "user"), required=True)
    args = parser.parse_args()

    password = getpass("New password (12+ characters): ")
    confirmation = getpass("Confirm password: ")
    if len(password) < 12:
        parser.error("Password must be at least 12 characters.")
    if password != confirmation:
        parser.error("Passwords do not match.")

    salt, password_hash = hash_password(password)
    initialize_web_schema()
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO web_users (username, password_salt, password_hash, role) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (username) DO NOTHING RETURNING id",
                (args.username.strip(), salt, password_hash, args.role),
            )
            created = cursor.fetchone()
    if created:
        print(f"Created {args.role} account: {args.username}")
    else:
        print(f"Account already exists; no changes made: {args.username}")


if __name__ == "__main__":
    main()
