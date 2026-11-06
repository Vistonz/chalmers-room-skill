from chalmers_room_skill.cli import build_parser


def test_cli_exposes_required_commands() -> None:
    parser = build_parser()
    for command in ("login", "bookings", "rooms", "book", "session"):
        args = parser.parse_args([command])
        assert args.command == command
        assert callable(args.handler)


def test_bookings_command_defaults_to_my_bookings_url() -> None:
    parser = build_parser()
    args = parser.parse_args(["bookings"])
    assert args.url.endswith("/my.html")
    assert args.handler.__name__ == "command_bookings"

