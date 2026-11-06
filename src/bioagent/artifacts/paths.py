from pathlib import PureWindowsPath

_INVALID_WINDOWS_CHARACTERS = frozenset('<>:"\\|?*')
_RESERVED_WINDOWS_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{suffix}" for suffix in "123456789¹²³"),
        *(f"LPT{suffix}" for suffix in "123456789¹²³"),
    }
)


def validate_artifact_relative_path(value: str) -> tuple[str, ...]:
    windows_path = PureWindowsPath(value)
    parts = value.split("/")
    if (
        not value
        or windows_path.drive
        or windows_path.root
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("invalid artifact relative path")

    for part in parts:
        if part.endswith((" ", ".")):
            raise ValueError("invalid artifact relative path")
        if any(
            character in _INVALID_WINDOWS_CHARACTERS or ord(character) < 32
            for character in part
        ):
            raise ValueError("invalid artifact relative path")

        device_stem = part.split(".", maxsplit=1)[0].rstrip(" .").upper()
        if device_stem in _RESERVED_WINDOWS_NAMES:
            raise ValueError("invalid artifact relative path")

    return tuple(parts)
