from __future__ import annotations

import asyncio

from backend.app.seeds.seed_data import main as seed_main


if __name__ == "__main__":
    asyncio.run(seed_main())
