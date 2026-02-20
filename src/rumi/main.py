"""Rumi entry point."""

import asyncio
import sys

from dotenv import find_dotenv, load_dotenv

from .cli import run_cli


def main() -> None:
    """Main entry point."""
    load_dotenv(find_dotenv(usecwd=True))

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "bot":
            from .telegram import TelegramBot

            bot = TelegramBot()
            bot.run()
            return

        if command == "skills":
            from .skills.cli import run_skills_cli

            # Pass remaining args (after 'skills') to skills CLI
            sys.exit(run_skills_cli(sys.argv[2:]))

    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
