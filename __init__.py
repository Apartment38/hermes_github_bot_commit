"""Native Hermes plugin entry point. Registration does no filesystem or network I/O."""

from .github_bot import cli, middleware, setup_parser


def register(ctx):
    ctx.register_middleware("tool_request", middleware)
    ctx.register_cli_command(
        "github-bot-commit", "Configure GitHub commit identity", setup_parser, cli
    )
