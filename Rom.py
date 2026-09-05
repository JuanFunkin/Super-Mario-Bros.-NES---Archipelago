import settings
from worlds.Files import APProcedurePatch, APTokenMixin


class SMB1Settings(settings.Group):
    class RomFile(settings.UserFilePath):
        """Locate your legally-owned Super Mario Bros. (NES) ROM, unmodified."""
        description = "Super Mario Bros. (NES) ROM File"
        copy_to = "Super Mario Bros.nes"

    rom_file: RomFile = RomFile(RomFile.copy_to)


class SMB1ProcedurePatch(APProcedurePatch, APTokenMixin):
    game = "Super Mario Bros."
    hash = None
    patch_file_ending = ".apsmb1"
    result_file_ending = ".nes"

    procedure = [
        ("apply_tokens", ["token_data"]),
    ]

    @classmethod
    def get_source_data(cls) -> bytes:
        return get_base_rom_bytes()

    def patch(self, target: str) -> None:
        # This game doesn't need any ROM modification (everything happens
        # through RAM reads/writes), so instead of relying on the token
        # engine with an empty stream, we just copy the base ROM straight
        # to the destination.
        with open(target, "wb") as f:
            f.write(self.get_source_data())


def get_base_rom_bytes() -> bytes:
    # late import to avoid a circular import with __init__.py
    from . import SMB1World
    file_name = SMB1World.settings.rom_file
    with open(file_name, "rb") as f:
        return bytes(f.read())
