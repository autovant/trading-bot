    # --------------------------------------------------------------------- #
    # Strategies
    # --------------------------------------------------------------------- #

    async def create_strategy(self, strategy: Strategy) -> Optional[int]:
        if not self.connection:
            return None
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                """
                INSERT INTO strategies (name, config, is_active)
                VALUES (?, ?, ?)
            """,
                (
                    strategy.name,
                    json.dumps(strategy.config),
                    _bool_to_int(strategy.is_active),
                ),
            )
            self.connection.commit()
            return cursor.lastrowid
        except Exception as exc:
            logger.error("Error creating strategy: %s", exc)
            return None

    async def get_strategy(self, name: str) -> Optional[Strategy]:
        if not self.connection:
            return None
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM strategies WHERE name = ?", (name,))
            row = cursor.fetchone()
            if not row:
                return None
            return Strategy(
                id=row["id"],
                name=row["name"],
                config=json.loads(row["config"]),
                is_active=bool(row["is_active"]),
                created_at=_row_datetime(row["created_at"]),
                updated_at=_row_datetime(row["updated_at"]),
            )
        except Exception as exc:
            logger.error("Error fetching strategy: %s", exc)
            return None

    async def list_strategies(self) -> List[Strategy]:
        if not self.connection:
            return []
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM strategies ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [
                Strategy(
                    id=row["id"],
                    name=row["name"],
                    config=json.loads(row["config"]),
                    is_active=bool(row["is_active"]),
                    created_at=_row_datetime(row["created_at"]),
                    updated_at=_row_datetime(row["updated_at"]),
                )
                for row in rows
            ]
        except Exception as exc:
            logger.error("Error listing strategies: %s", exc)
            return []

    async def update_strategy(self, strategy: Strategy) -> bool:
        if not self.connection:
            return False
        try:
            cursor = self.connection.cursor()
            
            # If setting as active, deactivate others
            if strategy.is_active:
                cursor.execute("UPDATE strategies SET is_active = 0")

            cursor.execute(
                """
                UPDATE strategies
                SET config = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
            """,
                (
                    json.dumps(strategy.config),
                    _bool_to_int(strategy.is_active),
                    strategy.name,
                ),
            )
            self.connection.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Error updating strategy: %s", exc)
            return False

    async def delete_strategy(self, name: str) -> bool:
        if not self.connection:
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM strategies WHERE name = ?", (name,))
            self.connection.commit()
            return cursor.rowcount > 0
        except Exception as exc:
            logger.error("Error deleting strategy: %s", exc)
            return False
