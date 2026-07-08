from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.achievements.models import CodeNote
from apps.games.models import Console, Game

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12
IMPORT_AUTHOR = "ra-import"

# Public RetroAchievements code notes for Crash Bandicoot (game id 10434).
# Source: https://retroachievements.org/codenotes.php?g=10434
CODE_NOTES = [
    ('0x54b84', 'Frames'),
    ('0x56400', '01 - Game Paused'),
    ('0x5e720', 'Controller Inputs Part 1:\nBit0 - L2\nBit1 - R2\nBit2 - L1\nBit3 - R1\nBit4 - Triangle\nBit5 - Circle\nBit6 - Cross\nBit7 - Square'),
    ('0x5e721', 'Controller Inputs Part 2:\nBit0 - Select\nBit1 - L3\nBit2 - R3\nBit3 - Start\nBit4 - DPAD Up\nBit5 - DPAD Right\nBit6 - DPAD Down\nBit7 - DPAD Left'),
    ('0x60ddc', "[24-bit Pointer]\n+0x105 | Papu Papu\n0x03 = Max Health\n-------------------------\n+0x6c |\n.+0x68 |\n..+0x105 | [8bit] Ripper Roo Health\n0x03 = Max Health\n-------------------------\n+0x105 | Pinstripe Potoroo Health\n0x06 = Max Health\n-------------------------\n+0x105 | [8bit] Dr. Neo Cortex and Nitrus Brio Health\n0x05 = Max Health\n\nNote: this variable increments with each hit, up to a maximum of 5. It functions as a hit counter rather than a countdown.\n+6c |\n.+0x105 | [8bit] Actual Cortex Health - This pointer correctly reflects Cortex's logical health, but it breaks as soon as the fight with Crash begins. It only updates again when Crash dies, then immediately breaks once the fight restarts."),
    ('0x60e1a', 'Big TNT moving pattern (left column moves down, ?)'),
    ('0x61665', 'Number of crates broken/missed (EU)'),
    ('0x61678', '01: On results screen/you died after first checkpoint (EU)'),
    ('0x61898', '[24-bit Pointer]\n+0x6c |\n.+0x105 | Koala Kong Health'),
    ('0x618a4', '[24-bit Pointer]\n+0x6c |\n.+0xe4 |\n..+0x0c | [8-bit] Wumpa Fruits'),
    ('0x618a8', '[24-bit Pointer]\n+0x06 |\n.+0xe4 |\n..+0x0c | [8-bit] Live Counter'),
    ('0x618cc', "[24-bit Pointer]\n+0x80 | [32-bit] Aku Aku's X Position\n+0x84 | [32-bit] Aku Aku's Y Position\n+0x88 | [32-bit] Aku Aku's Z Position\n\n+0x189 | Aku Aku Shield Level\n0x01 = Level 1\n\n----- Debug -----\n+0xe0 | [32-bit] Invincible Crash (freeze this value after acquiring Aku Aku shield, unfreeze upon finishing the level)"),
    ('0x618ed', 'Lives Countrer (Map)'),
    ('0x618f1', 'Aku Aku (Map)'),
    ('0x618f5', 'Wumpas (Map)'),
    ('0x61920', 'Camera Position X (32-Bit)'),
    ('0x61924', 'Camera Position Y (32-Bit)'),
    ('0x61930', 'Something Cutscene Related?'),
    ('0x61974', 'Game Progress (Value only changes when Game Progress is show on screen)'),
    ('0x6197c', 'Current Bonus Stage:\n00 - Tawna Bonus Stage 1 (Jungle Rollers)\n04 - Tawna Bonus Stage 2 (The Great Gate)\n0A - Tawna Bonus Stage 3 (Upstream)\n08 - Tawna Bonus Stage 4 (Rolling Stones)\n01 - Tawna Bonus Stage 5 (Native Fortress)\n0B - Tawna Bonus Stage 6 (Up the Creek)\n0C - Tawna Bonus Stage 7 (The Lost City)\n0D - Tawna Bonus Stage 8 (Road To Nowhere)\n05 - Tawna Bonus Stage 9 (Sunset Vista)\n12 - Tawna Bonus Stage 10 (Heavy Machinery)\n0B - Tawna Bonus Stage 11 (Generator Room)\n06 - Tawna Bonus Stage 12 (Toxic Waste)\n03 - Tawna Bonus Stage 13 (The High Road)\n11 - Tawna Bonus Stage 14 (Jaws of Darkness)\n13 - Tawna Bonus Stage 15 (The Lab)\n\n0E - Brio Bonus Stage 1 (Rolling Stones)\n07 - Brio Bonus Stage 2 (The Lost City)\n15 - Brio Bonus Stage 3 (Heavy Machinery)\n14 - Brio Bonus Stage 4 (Slippery Climb)\n\n09 - Cortex Bonus Stage 1 (Sunset Vista)\n0F - Cortex Bonus Stage 2 (Jaws Of Darkness)'),
    ('0x61985', 'Ammount of boxes destroyed/missed'),
    ('0x61988', 'Gems Collected Part 1:\nBit0 - ???\nBit1 - N. Sanity Beach\nBit2 - Jungle Rollers\nBit3 - The Great Gate\nBit4 - Boulders\nBit5 - Upstream\nBit6 - Papu Papu (NO GEM)\nBit7 - Rolling Stones'),
    ('0x61989', 'Gems Collected Part 2:\nBit0 - Hog Wild\nBit1 - Native Fortress\nBit2 - Up The Creek\nBit3 - Ripper Roo (NO GEM)\nBit4 - The Lost City (Green Gem)\nBit5 - Temple Ruins\nBit6 - Road To Nowhere\nBit7 - Boulder Dash'),
    ('0x6198a', 'Gems Collected Part 3:\nBit0 - Sunset Vista\nBit1 - Koala Kong (NO GEM)\nBit2 - Heavy Machinery\nBit3 - Cortex Power\nBit4 - Generator Room (Orange Gem)\nBit5 - Toxic Waste (Blue Gem)\nBit6 - Pinstripe (NO GEM)\nBit7 - The High Road'),
    ('0x6198b', 'Gems Collected Part 4:\nBit0 - Slippery Climb (Red)\nBit1 - Lights Out (Purple)\nBit2 - Flumbling In The Dark\nBit3 - Castle Machinery\nBit4 - Nitrus Brio (NO GEM)\nBit5 - The Lab (Yellow)'),
    ('0x61994', 'Overworld Status:\n00 - In a Stage\n01 - On the Map\n05 - Going To The Previous World\n06 - Going To The Next World'),
    ('0x61998', 'On Results Screen'),
    ('0x619ad', 'Key/Gem Collected Part 1:\nBit0 - Fumbling in the Dark Gem\nBit2 - Jaws Of Darkness Key'),
    ('0x619ae', 'Key/Gem Collected Part 2:\nBit 2 - Whole Hog Gem\nBit4 - Sunset Vista Key'),
    ('0x619c5', 'Stage Select/Current Stage:\n00 - N. Sanity Beach\n01 - Jungle Rollers\n02 - The Great Gate\n03 - Boulders\n04 - Upstream\n05 - Papu Papu\n06 - Rolling Stones\n07 - Hog Wild\n08 - Native Fortress\n09 - Up The Creek\n0A - Ripper Roo\n0B - The Lost City\n0C - Temple Ruins\n0D - Road To Nowhere\n0E - Boulder Dash\n0F - Sunset Vista\n10 - Koala Kong\n11 - Heavy Machinery\n12 - Cortex Power\n13 - Generator Room\n14 - Toxic Waste\n15 - Pinstripe\n16 - The High Road\n17 - Slippery Climb\n18 - Lights Out\n19 - Jaws of Darkness\n1A - Castle Machinery\n1B - Nitrus Brio\n1C - The Lab\n1D - The Great Wall\n1E - Dr. Neo Cortex\n1F - Flumbling In The Dark\n20 - Whole Hog'),
    ('0x61a10', 'Gems (Value only changes when Game Progress is show on screen)'),
    ('0x61a68', 'FF - Finished/Quited a Level (Kinda)'),
    ('0x90501', "Pinstripe's health (EU)"),
    ('0x9069d', "Papu Papu's health (EU)"),
    ('0x9080d', 'Pinstripe Potoroo Gun Shoots Thing (First Try)'),
    ('0x9081d', 'Pinstripe Potoroo Health (First Try)'),
    ('0x90820', 'Pinstripe Potoroo Animations (First Try)'),
    ('0x909b9', 'Papu Papu Health (First Try)'),
    ('0x909bc', 'Papu Papu Animation (First Try)'),
    ('0x91162', 'Aku Aku level (Dr. Nitrus Brio) (EU)'),
    ('0x9119d', 'Nitru Brio Health (First Try)'),
    ('0x9147d', 'Aku Aku (Nitrus Brio)'),
    ('0x914d5', "Ripper Roo's health (uneditable) (EU)"),
    ('0x914e9', "Cortex's health (uneditable) (EU)"),
    ('0x91615', 'Aku Aku level (Koala Kong) (EU)'),
    ('0x9164d', 'Koala Kong Health (First Try)'),
    ('0x917f1', 'Ripper Roo Health (First Try)'),
    ('0x91809', 'Dr. Neo Cortex Health (First Try)'),
    ('0x91865', 'Aku Aku (Papu Papu)'),
    ('0x9192d', 'Aku Aku (Koala Kong)'),
    ('0x91a11', 'Aku Aku level (Ripper Roo) (EU)'),
    ('0x91a94', 'Lives Countrer (N. Sanity Beach)'),
    ('0x91ad5', 'Aku Aku (Jungle Rollers)'),
    ('0x9203d', 'Aku Aku (Temple Ruins)'),
    ('0x92485', 'Aku Aku (Upstream)'),
    ('0x92579', 'Aku Aku level (N. Sanity Beach) (EU)'),
    ('0x92679', 'Aku Aku (Native Fortress)'),
    ('0x926e9', 'Aku Aku level (Up the creek)(EU)'),
    ('0x927a5', 'Aku Aku (Up The Creek)'),
    ('0x92899', 'Aku Aku (N. Sanity Beach)'),
    ('0x92ab1', 'Aku Aku (The Great Gate)'),
    ('0x92b6d', 'Aku Aku (Dr. Neo Cortex)'),
    ('0x93699', "Koala Kong's health (EU)"),
    ('0x939f5', 'Aku Aku (Rolling Stones)'),
    ('0x93ebd', 'Aku Aku (Road To Nowhere)'),
    ('0x9456d', 'Aku Aku (Sunset Vista)'),
    ('0x95ded', 'Aku Aku (The Lost City)'),
    ('0x973f5', "Brio's health (uneditable) (EU)"),
    ('0x9ddc1', 'Wumpa fruit (Ripper Roo) (EU)'),
    ('0x9ddc5', 'Lives (Ripper Roo) (EU)'),
    ('0x9de7d', 'Wumpa fruit (Koala Kong) (EU)'),
    ('0x9de81', 'Lives (Koala Kong) (EU)\nWumpa fruit (Nitrus Brio) (EU)'),
    ('0x9de85', 'Lives (Dr. Nitrus Brio) (EU)'),
    ('0x9e0d1', 'Papu Papu lives counter.'),
    ('0x9e0e1', 'Ripper Roo lives counter.'),
    ('0x9e0f9', 'Dr. Neo Cortex lives counter.'),
    ('0x9e191', 'Pinstripe lives counter.'),
    ('0x9e199', 'Koala Kong lives counter.'),
    ('0x9e1a1', 'Nitrus Brio lives counter.'),
    ('0x9e215', 'Wumpa fruit (EU)'),
    ('0x9e219', 'Lives (EU)'),
    ('0x9e369', 'The Great Hall lives counter.'),
    ('0x9e4cd', 'Toxic Waste lives counter.'),
    ('0x9e509', 'Lights Out lives counter.'),
    ('0x9e525', 'Crash Animations (N. Sanity Beach)'),
    ('0x9e52d', 'The Lab lives counter.'),
    ('0x9e535', 'Wumpas (N. Sanity Beach)'),
    ('0x9e54d', 'Generator Room lives counter.'),
    ('0x9e585', 'Boulders lives counter.'),
    ('0x9e59d', "Jungle Roller's lives counter."),
    ('0x9e5ad', 'Fumbling in the Dark lives counter.'),
    ('0x9e5cd', 'The High Road lives counter.'),
    ('0x9e5dd', 'Upstream lives counter.'),
    ('0x9e5f1', 'Slippery Climb lives counter.'),
    ('0x9e611', 'Rolling Stones lives counter.'),
    ('0x9e615', 'Whole Hog lives counter.'),
    ('0x9e621', 'Road to Nowhere lives counter.'),
    ('0x9e64d', 'Hog Wild/Temple Ruins lives counter.'),
    ('0x9e6a1', 'Up the Creek lives counter.'),
    ('0x9e6a5', 'The Lost City lives counter.'),
    ('0x9e751', 'The Great Gate Lives counter.'),
    ('0x9e779', 'Jaws of Darkness lives counter.'),
    ('0x9e77d', 'Cortex Power lives counter.'),
    ('0x9e7d1', 'Native Fortress lives counter.'),
    ('0x9e809', 'Boulder Dash lives counter.'),
    ('0x9e819', 'Sunset Vista lives counter.'),
    ('0x9e829', 'Heavy Machinery lives counter.'),
    ('0x9e88d', 'Castle Machinery lives counter.'),
]


class Command(BaseCommand):
    help = "Seed the Crash Bandicoot 1 RetroAchievements code notes as CodeNote rows (idempotent)."

    def handle(self, *args, **options):
        console, _ = Console.objects.get_or_create(
            ra_id=PS1_RA_ID, defaults={"name": "PlayStation", "short_name": "PS1"}
        )
        game, _ = Game.objects.get_or_create(title=GAME_TITLE, defaults={"console": console})
        author, _ = get_user_model().objects.get_or_create(
            username=IMPORT_AUTHOR, defaults={"is_active": False}
        )

        existing = set(CodeNote.objects.filter(game=game).values_list("address", flat=True))
        created = CodeNote.objects.bulk_create(
            [
                CodeNote(game=game, author=author, address=address, note=note)
                for address, note in CODE_NOTES
                if address not in existing
            ]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(created)} code notes "
                f"({len(CODE_NOTES)} total, {len(existing)} already present)."
            )
        )
