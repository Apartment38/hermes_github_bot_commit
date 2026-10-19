"""Native Hermes plugin entry point. Registration does no filesystem or network I/O."""

from .github_bot import cli, middleware, setup_parser


def register(ctx):
    def tool_request(tool_name=None, args=None, **kwargs):
        return middleware(ctx, tool_name=tool_name, args=args, **kwargs)

    def command(args):
        return cli(ctx, args)

    ctx.register_middleware("tool_request", tool_request)
    ctx.register_cli_command(
        "github-bot-commit", "Configure GitHub commit identity", setup_parser, command
    )
