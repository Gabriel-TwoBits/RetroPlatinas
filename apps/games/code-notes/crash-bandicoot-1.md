# Crash Bandicoot 1 — Memory Map (Code Notes)

> **Source:** RetroAchievements code notes for *Crash Bandicoot* (PlayStation), game id 10434 — <https://retroachievements.org/codenotes.php?g=10434>  
> **Community authors:** matheus2653, CySlaytor, Alfex, msdmario, TheJediSonic.

RetroAchievements maps system memory at `$00000000` immediately followed by cartridge memory, so the addresses below may not correspond to real-hardware addresses. The `Type` column is inferred from each note's text and is best-effort. Seed these notes into the database as `CodeNote` rows with `python manage.py seed_crash1_code_notes` (idempotent).

## Key addresses

| Address | Type | Description |
| --- | --- | --- |
| `0x619c5` | enum/flag | Current stage (00 = N. Sanity Beach, 01 = Jungle Rollers, ...) |
| `0x61994` | enum/flag | Overworld status (00 = in a stage, 01 = on the map) |
| `0x9e215` | 8-bit | Wumpa fruit count |
| `0x9e219` | 8-bit | Lives |
| `0x61988` | bitfield | Gems collected bitfield, part 1 of 4 (0x61988-0x6198b) |
| `0x619ad` | bitfield | Keys/gems collected bitfield |
| `0x618cc` | pointer | Aku Aku pointer (shield level at +0x189) |
| `0x618a4` | pointer | Wumpa fruits (via pointer) |
| `0x618a8` | pointer | Lives counter (via pointer) |
| `0x61985` | 8-bit | Boxes destroyed/missed |
| `0x61665` | 8-bit | Crates broken/missed (EU) |
| `0x60ddc` | pointer | Boss health pointer (Papu/Ripper/Pinstripe/Cortex/Brio) |
| `0x6197c` | enum/flag | Current bonus stage |
| `0x61974` | 8-bit | Game progress (updates on progress screen) |
| `0x61a10` | 8-bit | Gems total (updates on progress screen) |
| `0x61a68` | enum/flag | FF = finished/quit a level |
| `0x61998` | 8-bit | On results screen |
| `0x54b84` | 8-bit | Frames |

## All code notes (108)

| Address | Type | Note |
| --- | --- | --- |
| `0x54b84` | 8-bit | Frames |
| `0x56400` | enum/flag | 01 - Game Paused |
| `0x5e720` | bitfield | Controller Inputs Part 1:<br>Bit0 - L2<br>Bit1 - R2<br>Bit2 - L1<br>Bit3 - R1<br>Bit4 - Triangle<br>Bit5 - Circle<br>Bit6 - Cross<br>Bit7 - Square |
| `0x5e721` | bitfield | Controller Inputs Part 2:<br>Bit0 - Select<br>Bit1 - L3<br>Bit2 - R3<br>Bit3 - Start<br>Bit4 - DPAD Up<br>Bit5 - DPAD Right<br>Bit6 - DPAD Down<br>Bit7 - DPAD Left |
| `0x60ddc` | pointer | [24-bit Pointer]<br>+0x105 \| Papu Papu<br>0x03 = Max Health<br>-------------------------<br>+0x6c \|<br>.+0x68 \|<br>..+0x105 \| [8bit] Ripper Roo Health<br>0x03 = Max Health<br>-------------------------<br>+0x105 \| Pinstripe Potoroo Health<br>0x06 = Max Health<br>-------------------------<br>+0x105 \| [8bit] Dr. Neo Cortex and Nitrus Brio Health<br>0x05 = Max Health<br><br>Note: this variable increments with each hit, up to a maximum of 5. It functions as a hit counter rather than a countdown.<br>+6c \|<br>.+0x105 \| [8bit] Actual Cortex Health - This pointer correctly reflects Cortex's logical health, but it breaks as soon as the fight with Crash begins. It only updates again when Crash dies, then immediately breaks once the fight restarts. |
| `0x60e1a` | 8-bit | Big TNT moving pattern (left column moves down, ?) |
| `0x61665` | 8-bit | Number of crates broken/missed (EU) |
| `0x61678` | enum/flag | 01: On results screen/you died after first checkpoint (EU) |
| `0x61898` | pointer | [24-bit Pointer]<br>+0x6c \|<br>.+0x105 \| Koala Kong Health |
| `0x618a4` | pointer | [24-bit Pointer]<br>+0x6c \|<br>.+0xe4 \|<br>..+0x0c \| [8-bit] Wumpa Fruits |
| `0x618a8` | pointer | [24-bit Pointer]<br>+0x06 \|<br>.+0xe4 \|<br>..+0x0c \| [8-bit] Live Counter |
| `0x618cc` | pointer | [24-bit Pointer]<br>+0x80 \| [32-bit] Aku Aku's X Position<br>+0x84 \| [32-bit] Aku Aku's Y Position<br>+0x88 \| [32-bit] Aku Aku's Z Position<br><br>+0x189 \| Aku Aku Shield Level<br>0x01 = Level 1<br><br>----- Debug -----<br>+0xe0 \| [32-bit] Invincible Crash (freeze this value after acquiring Aku Aku shield, unfreeze upon finishing the level) |
| `0x618ed` | 8-bit | Lives Countrer (Map) |
| `0x618f1` | 8-bit | Aku Aku (Map) |
| `0x618f5` | 8-bit | Wumpas (Map) |
| `0x61920` | 32-bit | Camera Position X (32-Bit) |
| `0x61924` | 32-bit | Camera Position Y (32-Bit) |
| `0x61930` | 8-bit | Something Cutscene Related? |
| `0x61974` | 8-bit | Game Progress (Value only changes when Game Progress is show on screen) |
| `0x6197c` | enum/flag | Current Bonus Stage:<br>00 - Tawna Bonus Stage 1 (Jungle Rollers)<br>04 - Tawna Bonus Stage 2 (The Great Gate)<br>0A - Tawna Bonus Stage 3 (Upstream)<br>08 - Tawna Bonus Stage 4 (Rolling Stones)<br>01 - Tawna Bonus Stage 5 (Native Fortress)<br>0B - Tawna Bonus Stage 6 (Up the Creek)<br>0C - Tawna Bonus Stage 7 (The Lost City)<br>0D - Tawna Bonus Stage 8 (Road To Nowhere)<br>05 - Tawna Bonus Stage 9 (Sunset Vista)<br>12 - Tawna Bonus Stage 10 (Heavy Machinery)<br>0B - Tawna Bonus Stage 11 (Generator Room)<br>06 - Tawna Bonus Stage 12 (Toxic Waste)<br>03 - Tawna Bonus Stage 13 (The High Road)<br>11 - Tawna Bonus Stage 14 (Jaws of Darkness)<br>13 - Tawna Bonus Stage 15 (The Lab)<br><br>0E - Brio Bonus Stage 1 (Rolling Stones)<br>07 - Brio Bonus Stage 2 (The Lost City)<br>15 - Brio Bonus Stage 3 (Heavy Machinery)<br>14 - Brio Bonus Stage 4 (Slippery Climb)<br><br>09 - Cortex Bonus Stage 1 (Sunset Vista)<br>0F - Cortex Bonus Stage 2 (Jaws Of Darkness) |
| `0x61985` | 8-bit | Ammount of boxes destroyed/missed |
| `0x61988` | bitfield | Gems Collected Part 1:<br>Bit0 - ???<br>Bit1 - N. Sanity Beach<br>Bit2 - Jungle Rollers<br>Bit3 - The Great Gate<br>Bit4 - Boulders<br>Bit5 - Upstream<br>Bit6 - Papu Papu (NO GEM)<br>Bit7 - Rolling Stones |
| `0x61989` | bitfield | Gems Collected Part 2:<br>Bit0 - Hog Wild<br>Bit1 - Native Fortress<br>Bit2 - Up The Creek<br>Bit3 - Ripper Roo (NO GEM)<br>Bit4 - The Lost City (Green Gem)<br>Bit5 - Temple Ruins<br>Bit6 - Road To Nowhere<br>Bit7 - Boulder Dash |
| `0x6198a` | bitfield | Gems Collected Part 3:<br>Bit0 - Sunset Vista<br>Bit1 - Koala Kong (NO GEM)<br>Bit2 - Heavy Machinery<br>Bit3 - Cortex Power<br>Bit4 - Generator Room (Orange Gem)<br>Bit5 - Toxic Waste (Blue Gem)<br>Bit6 - Pinstripe (NO GEM)<br>Bit7 - The High Road |
| `0x6198b` | bitfield | Gems Collected Part 4:<br>Bit0 - Slippery Climb (Red)<br>Bit1 - Lights Out (Purple)<br>Bit2 - Flumbling In The Dark<br>Bit3 - Castle Machinery<br>Bit4 - Nitrus Brio (NO GEM)<br>Bit5 - The Lab (Yellow) |
| `0x61994` | enum/flag | Overworld Status:<br>00 - In a Stage<br>01 - On the Map<br>05 - Going To The Previous World<br>06 - Going To The Next World |
| `0x61998` | 8-bit | On Results Screen |
| `0x619ad` | bitfield | Key/Gem Collected Part 1:<br>Bit0 - Fumbling in the Dark Gem<br>Bit2 - Jaws Of Darkness Key |
| `0x619ae` | bitfield | Key/Gem Collected Part 2:<br>Bit 2 - Whole Hog Gem<br>Bit4 - Sunset Vista Key |
| `0x619c5` | enum/flag | Stage Select/Current Stage:<br>00 - N. Sanity Beach<br>01 - Jungle Rollers<br>02 - The Great Gate<br>03 - Boulders<br>04 - Upstream<br>05 - Papu Papu<br>06 - Rolling Stones<br>07 - Hog Wild<br>08 - Native Fortress<br>09 - Up The Creek<br>0A - Ripper Roo<br>0B - The Lost City<br>0C - Temple Ruins<br>0D - Road To Nowhere<br>0E - Boulder Dash<br>0F - Sunset Vista<br>10 - Koala Kong<br>11 - Heavy Machinery<br>12 - Cortex Power<br>13 - Generator Room<br>14 - Toxic Waste<br>15 - Pinstripe<br>16 - The High Road<br>17 - Slippery Climb<br>18 - Lights Out<br>19 - Jaws of Darkness<br>1A - Castle Machinery<br>1B - Nitrus Brio<br>1C - The Lab<br>1D - The Great Wall<br>1E - Dr. Neo Cortex<br>1F - Flumbling In The Dark<br>20 - Whole Hog |
| `0x61a10` | 8-bit | Gems (Value only changes when Game Progress is show on screen) |
| `0x61a68` | enum/flag | FF - Finished/Quited a Level (Kinda) |
| `0x90501` | 8-bit | Pinstripe's health (EU) |
| `0x9069d` | 8-bit | Papu Papu's health (EU) |
| `0x9080d` | 8-bit | Pinstripe Potoroo Gun Shoots Thing (First Try) |
| `0x9081d` | 8-bit | Pinstripe Potoroo Health (First Try) |
| `0x90820` | 8-bit | Pinstripe Potoroo Animations (First Try) |
| `0x909b9` | 8-bit | Papu Papu Health (First Try) |
| `0x909bc` | 8-bit | Papu Papu Animation (First Try) |
| `0x91162` | 8-bit | Aku Aku level (Dr. Nitrus Brio) (EU) |
| `0x9119d` | 8-bit | Nitru Brio Health (First Try) |
| `0x9147d` | 8-bit | Aku Aku (Nitrus Brio) |
| `0x914d5` | 8-bit | Ripper Roo's health (uneditable) (EU) |
| `0x914e9` | 8-bit | Cortex's health (uneditable) (EU) |
| `0x91615` | 8-bit | Aku Aku level (Koala Kong) (EU) |
| `0x9164d` | 8-bit | Koala Kong Health (First Try) |
| `0x917f1` | 8-bit | Ripper Roo Health (First Try) |
| `0x91809` | 8-bit | Dr. Neo Cortex Health (First Try) |
| `0x91865` | 8-bit | Aku Aku (Papu Papu) |
| `0x9192d` | 8-bit | Aku Aku (Koala Kong) |
| `0x91a11` | 8-bit | Aku Aku level (Ripper Roo) (EU) |
| `0x91a94` | 8-bit | Lives Countrer (N. Sanity Beach) |
| `0x91ad5` | 8-bit | Aku Aku (Jungle Rollers) |
| `0x9203d` | 8-bit | Aku Aku (Temple Ruins) |
| `0x92485` | 8-bit | Aku Aku (Upstream) |
| `0x92579` | 8-bit | Aku Aku level (N. Sanity Beach) (EU) |
| `0x92679` | 8-bit | Aku Aku (Native Fortress) |
| `0x926e9` | 8-bit | Aku Aku level (Up the creek)(EU) |
| `0x927a5` | 8-bit | Aku Aku (Up The Creek) |
| `0x92899` | 8-bit | Aku Aku (N. Sanity Beach) |
| `0x92ab1` | 8-bit | Aku Aku (The Great Gate) |
| `0x92b6d` | 8-bit | Aku Aku (Dr. Neo Cortex) |
| `0x93699` | 8-bit | Koala Kong's health (EU) |
| `0x939f5` | 8-bit | Aku Aku (Rolling Stones) |
| `0x93ebd` | 8-bit | Aku Aku (Road To Nowhere) |
| `0x9456d` | 8-bit | Aku Aku (Sunset Vista) |
| `0x95ded` | 8-bit | Aku Aku (The Lost City) |
| `0x973f5` | 8-bit | Brio's health (uneditable) (EU) |
| `0x9ddc1` | 8-bit | Wumpa fruit (Ripper Roo) (EU) |
| `0x9ddc5` | 8-bit | Lives (Ripper Roo) (EU) |
| `0x9de7d` | 8-bit | Wumpa fruit (Koala Kong) (EU) |
| `0x9de81` | 8-bit | Lives (Koala Kong) (EU)<br>Wumpa fruit (Nitrus Brio) (EU) |
| `0x9de85` | 8-bit | Lives (Dr. Nitrus Brio) (EU) |
| `0x9e0d1` | 8-bit | Papu Papu lives counter. |
| `0x9e0e1` | 8-bit | Ripper Roo lives counter. |
| `0x9e0f9` | 8-bit | Dr. Neo Cortex lives counter. |
| `0x9e191` | 8-bit | Pinstripe lives counter. |
| `0x9e199` | 8-bit | Koala Kong lives counter. |
| `0x9e1a1` | 8-bit | Nitrus Brio lives counter. |
| `0x9e215` | 8-bit | Wumpa fruit (EU) |
| `0x9e219` | 8-bit | Lives (EU) |
| `0x9e369` | 8-bit | The Great Hall lives counter. |
| `0x9e4cd` | 8-bit | Toxic Waste lives counter. |
| `0x9e509` | 8-bit | Lights Out lives counter. |
| `0x9e525` | 8-bit | Crash Animations (N. Sanity Beach) |
| `0x9e52d` | 8-bit | The Lab lives counter. |
| `0x9e535` | 8-bit | Wumpas (N. Sanity Beach) |
| `0x9e54d` | 8-bit | Generator Room lives counter. |
| `0x9e585` | 8-bit | Boulders lives counter. |
| `0x9e59d` | 8-bit | Jungle Roller's lives counter. |
| `0x9e5ad` | 8-bit | Fumbling in the Dark lives counter. |
| `0x9e5cd` | 8-bit | The High Road lives counter. |
| `0x9e5dd` | 8-bit | Upstream lives counter. |
| `0x9e5f1` | 8-bit | Slippery Climb lives counter. |
| `0x9e611` | 8-bit | Rolling Stones lives counter. |
| `0x9e615` | 8-bit | Whole Hog lives counter. |
| `0x9e621` | 8-bit | Road to Nowhere lives counter. |
| `0x9e64d` | 8-bit | Hog Wild/Temple Ruins lives counter. |
| `0x9e6a1` | 8-bit | Up the Creek lives counter. |
| `0x9e6a5` | 8-bit | The Lost City lives counter. |
| `0x9e751` | 8-bit | The Great Gate Lives counter. |
| `0x9e779` | 8-bit | Jaws of Darkness lives counter. |
| `0x9e77d` | 8-bit | Cortex Power lives counter. |
| `0x9e7d1` | 8-bit | Native Fortress lives counter. |
| `0x9e809` | 8-bit | Boulder Dash lives counter. |
| `0x9e819` | 8-bit | Sunset Vista lives counter. |
| `0x9e829` | 8-bit | Heavy Machinery lives counter. |
| `0x9e88d` | 8-bit | Castle Machinery lives counter. |
