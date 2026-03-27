"""Inicializar la base de datos de ContaBot."""
from __future__ import annotations

import sys
from pathlib import Path

# Asegurar que el paquete contabot sea importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contabot.db.connection import DB_PATH, get_engine
from contabot.db.models import Base


def main() -> None:
    """Crear todas las tablas e inicializar la base de datos."""
    # Crear directorio de datos si no existe
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    engine = get_engine()
    Base.metadata.create_all(engine)

    print(f"Base de datos inicializada en: {DB_PATH}")
    print("Tablas creadas correctamente.")
    print("\nSiguiente paso: configura tu .env y ejecuta el bot:")
    print("  uvicorn contabot.bot.server:app --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    main()
