import unittest
from unittest.mock import patch

from backend.services import database


class DatabaseFallbackTests(unittest.TestCase):
    def test_init_pool_fails_gracefully_without_database(self):
        database._pool = None

        with patch(
            "backend.services.database.psycopg2.pool.ThreadedConnectionPool",
            side_effect=Exception("boom"),
        ):
            database.init_pool()

        self.assertIsNone(database._pool)


if __name__ == "__main__":
    unittest.main()
