from BaseClasses import Region
from .Locations import (
    SMB1Location, location_table, WORLDS, LEVELS, level_location_name,
    no_hit_location_name, MAX_COIN_CHECKS, MAX_ONEUP_CHECKS, MAX_KILL_CHECKS,
)


def create_regions(world) -> None:
    player = world.player
    multiworld = world.multiworld
    randomize_all = world.options.randomize_all_worlds.value
    coin_checks = world.options.coin_checks.value
    oneup_checks = world.options.oneup_checks.value
    kill_checks = world.options.kill_checks.value
    no_hit_checks = world.options.no_hit_checks.value

    menu = Region("Menu", player, multiworld)
    multiworld.regions.append(menu)

    worlds = WORLDS if randomize_all else range(1)
    previous_region = menu
    level_regions = {}

    # SMB1 is linear within each world, and worlds are played in order
    # (warp zones are ignored for now). We chain the 32 (or 4) locations
    # one after another: 1-1 -> 1-2 -> 1-3 -> 1-4 -> 2-1 -> ... -> 8-4
    for w in worlds:
        for l in LEVELS:
            name = level_location_name(w, l)
            region = Region(name, player, multiworld)
            loc = SMB1Location(player, name, location_table[name], region)
            region.locations.append(loc)
            multiworld.regions.append(region)
            level_regions[(w, l)] = region

            previous_region.connect(region, f"To {name}")
            previous_region = region

    # the last location generated is the goal (8-4 if randomize_all, otherwise 1-4)

    # Coin/1-Up/Kill locations: not tied to a specific level (they're global
    # milestones the client reports whenever they happen during the run),
    # so they hang off Menu, always accessible from the start.
    if coin_checks:
        for i in range(MAX_COIN_CHECKS):
            name = f"Coin Milestone #{i + 1}"
            loc = SMB1Location(player, name, location_table[name], menu)
            menu.locations.append(loc)

    if oneup_checks:
        for i in range(MAX_ONEUP_CHECKS):
            name = f"1-Up Get #{i + 1}"
            loc = SMB1Location(player, name, location_table[name], menu)
            menu.locations.append(loc)

    if kill_checks:
        for i in range(MAX_KILL_CHECKS):
            name = f"Stomp Kill Milestone #{i + 1}"
            loc = SMB1Location(player, name, location_table[name], menu)
            menu.locations.append(loc)

    # No-Hit Clear locations: tied to the level itself (same access as the
    # level's own "Complete" location), since you can only clear it without
    # damage after actually reaching/finishing that level.
    if no_hit_checks:
        for w in worlds:
            for l in LEVELS:
                name = no_hit_location_name(w, l)
                region = level_regions[(w, l)]
                loc = SMB1Location(player, name, location_table[name], region)
                region.locations.append(loc)
