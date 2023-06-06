"""
___________________________________________________________________

Genshin Impact Discord Rich Presence v0.1

Setup CONFIG.py with the game resolution, username, etc...
before using.

To exit, press Ctrl+C or close the terminal.
___________________________________________________________________
"""

from typing import Optional
from asyncio import new_event_loop, set_event_loop
import threading
import csv
import numpy as np
import easyocr
import time

import pypresence as discord
import ps_helper

from PIL import ImageGrab

from CONFIG import *
from datatypes import *

print(__doc__)

# Load csv tables

BOSSES: list[Boss] = None
CHARACTERS: list[Character] = None
DOMAINS: list[Domain] = None
LOCATIONS: list[Location] = None
try:
    with open("data/characters.csv", "r") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        CHARACTERS = []
        for row in reader:
            c = Character(*row)
            if (MC_AETHER and c.search_str == "aether") or (
                not MC_AETHER and c.search_str == "lumine"
            ):
                c.search_str = USERNAME.lower()
                c.character_display_name = USERNAME

            if c.search_str == "wanderer":
                c.search_str = WANDERER_NAME.lower()
                c.character_display_name = WANDERER_NAME

            CHARACTERS.append(c)
        print("Loaded characters.csv")
except Exception as e:
    print(f"Error loading data/characters.csv: {e}")

try:
    with open("data/domains.csv", "r") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        DOMAINS = [Domain(*row) for row in reader]
        print("Loaded domains.csv")
except Exception as e:
    print(f"Error loading data/domains.csv: {e}")

try:
    with open("data/locations.csv", "r") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        LOCATIONS = [Location(*row) for row in reader]
        print("Loaded locations.csv")
except Exception as e:
    print(f"Error loading data/locations.csv: {e}")

try:
    with open("data/bosses.csv", "r") as csvfile:
        reader = csv.reader(csvfile, delimiter=",")
        BOSSES = [Boss(*row) for row in reader]
        print("Loaded bosses.csv")
except Exception as e:
    print(f"Error loading data/bosses.csv: {e}")


current_active_character = 0  # 1-indexed. 0 is undetectable/game paused.

# TODO: Support variable number of characters.
current_characters: list[Character] = [None, None, None, None]

prev_non_idle_activity: Activity = Activity(ActivityType.LOADING, False)
"""
Stores most recent non-idle activity.

Non-idle activities are:
- Loading (assumes travelling in unknown location)
- Location
- Domain
- Commissions
- World Boss
"""

prev_location: Optional[Location] = None
"""
Stores most recently visited location (assumes commissions are here).
"""

current_activity: Activity = Activity(ActivityType.LOADING, False)

game_start_time: Optional[int] = None

game_paused = False
"""
True if the game is found to be paused in the previous iteration

(May not be accurate. Commit pause/resume state if game_pause_state_cooldown == 0)
"""

game_pause_state_cooldown = 0
"""
Only commit game paused/unpaused to `current_activity` if game_pause_state_cooldown == 0.

This value gets set to `CONFIG.PAUSE_STATE_COOLDOWN` when game is detected as paused/unpaused.
"""

game_pause_state_displayed = False
"""
Shows the last displayed game pause state.
(Needed to prevent spamming console with the same game paused/resumed message).
"""

domain_cooldown = 0
"""
Only detect domain if domain_cooldown == 0.

This value gets set to `CONFIG.PARTY_SETUP_DOMAIN_COOLDOWN` when party setup screen is detected,
and decremented each iteration.

"Party Setup" text could be missed by OCR, which causes 4th character in party to be read as domain.
To reduce CPU and prevent incorrect domain detection.
"""


"""

  _____  _____   _____   _____          ______ __  __  ____  _   _ 
 |  __ \|  __ \ / ____| |  __ \   /\   |  ____|  \/  |/ __ \| \ | |
 | |__) | |__) | |      | |  | | /  \  | |__  | \  / | |  | |  \| |
 |  _  /|  ___/| |      | |  | |/ /\ \ |  __| | |\/| | |  | | . ` |
 | | \ \| |    | |____  | |__| / ____ \| |____| |  | | |__| | |\  |
 |_|  \_\_|     \_____| |_____/_/    \_\______|_|  |_|\____/|_| \_|
                                                                   
                                                                   
"""

rpc_event_loop = new_event_loop()


def discord_rpc_loop():
    set_event_loop(rpc_event_loop)
    rpc: discord.Presence = None

    def init_discord_rpc():
        nonlocal rpc

        printed_wait = False
        while True:
            try:
                rpc = discord.Presence(DISC_APP_ID)
                rpc.connect()
                print("Connected to Discord Client!")
                break
            except discord.exceptions.DiscordNotFound:
                if not printed_wait:
                    printed_wait = True
                    print("Waiting for discord to start...")
                time.sleep(2.5)
            except Exception as e:
                print("Unknown error while attempting to initialize discord RPC:")
                print(e)
                time.sleep(2.5)

    previous_update = None
    """
    Contains previous parameters dict sent to rpc update function.

    Only update rpc if data is different.
    """

    updated_now = False

    while True:
        if rpc == None:
            init_discord_rpc()  # Waits for discord to open (Blocking)

        params = current_activity.to_update_params_dict()
        if current_activity.activity_type in [
            ActivityType.LOADING,
            ActivityType.COMMISSION,
            ActivityType.LOCATION,
        ]:
            params["start"] = game_start_time
        else:
            params["start"] = current_activity.start_time

        if current_active_character != 0:
            c = current_characters[current_active_character - 1]
            if c != None:
                params["small_image"] = c.image_key
                params["small_text"] = f"playing {c.character_display_name}"

        if previous_update != params:
            try:
                # print(f'updated rpc: {params}')
                rpc.update(**params)
                previous_update = params
                updated_now = True
            except discord.exceptions.InvalidID:
                # Discord closed mid game. Need to create a new Presence client connection instance.
                rpc.close()
                rpc = None
                continue
            except Exception as e:
                print("Error updating Discord RPC:")
                print(e)
        else:
            updated_now = False

        if updated_now:
            # Rate limit for UpdateActivity RPC is 5 updates / 20 seconds.
            time.sleep(5)
        else:
            # If no update sent, it's safe to increase refresh rate to check for changes in current activity.
            time.sleep(1)


rpc_thread = threading.Thread(daemon=True, target=discord_rpc_loop)
rpc_thread.start()


"""

   ____   _____ _____    _      ____   ____  _____     ______  _      ____   _____ _  _______ _   _  _______  
  / __ \ / ____|  __ \  | |    / __ \ / __ \|  __ \   / /  _ \| |    / __ \ / ____| |/ /_   _| \ | |/ ____\ \ 
 | |  | | |    | |__) | | |   | |  | | |  | | |__) | | || |_) | |   | |  | | |    | ' /  | | |  \| | |  __ | |
 | |  | | |    |  _  /  | |   | |  | | |  | |  ___/  | ||  _ <| |   | |  | | |    |  <   | | | . ` | | |_ || |
 | |__| | |____| | \ \  | |___| |__| | |__| | |      | || |_) | |___| |__| | |____| . \ _| |_| |\  | |__| || |
  \____/ \_____|_|  \_\ |______\____/ \____/|_|      | ||____/|______\____/ \_____|_|\_\_____|_| \_|\_____|| |
                                                      \_\                                                 /_/ 
                                                                                                              
"""

print("Initializing OCR.")
reader = easyocr.Reader(["en"], gpu=USE_GPU)
print("OCR started.")
print("_______________________________________________________________")

pause_ocr = False
"""
Set to true when genshin is minimized.
"""

ps_window_thread_instance: threading.Thread = None


def update_genshin_open_status():
    global pause_ocr

    if ps_helper.check_process_window_open(GENSHIN_WINDOW_CLASS, GENSHIN_WINDOW_NAME) and pause_ocr:
        pause_ocr = False
        print("GenshinImpact.exe resumed. Resuming OCR.")
    elif not ps_helper.check_process_window_open(GENSHIN_WINDOW_CLASS, GENSHIN_WINDOW_NAME) and not pause_ocr:
        pause_ocr = True
        print("GenshinImpact.exe minimized/closed. Pausing OCR.")

 
party_capture_cache = {}
world_boss_capture_cache = {}
location_capture_cache = {}

loop_count = 0

while True:
    if pause_ocr:
        time.sleep(2)
        # Threading looks redundant here, but it's not (see below)
        if (
            ps_window_thread_instance == None
            or not ps_window_thread_instance.is_alive()
        ):
            ps_window_thread_instance = threading.Thread(
                target=update_genshin_open_status,
                daemon=True,
            )
            ps_window_thread_instance.start()
        continue

    loop_count += 1

    curr_game_paused = False
    """
    True if the game is found to be paused in the current iteration (may not be accurate).
    """

    #### CAPTURE ACTIVE CHARACTER (every loop)

    try:
        charnumber_cap = [
            ImageGrab.grab(
                bbox=(
                    NUMBER_4P_COORD[i][0],
                    NUMBER_4P_COORD[i][1],
                    NUMBER_4P_COORD[i][0] + 1,
                    NUMBER_4P_COORD[i][1] + 1,
                )
            ).getpixel((0, 0))
            for i in range(4)
        ]
    except OSError:
        print(
            "OSError: Cannot capture screen. Try running as admin if this issue persists."
        )
        time.sleep(100)
        continue

    charnumber_brightness = [sum(rgb) for rgb in charnumber_cap]
    active_character = [
        idx
        for idx, bri in enumerate(charnumber_brightness)
        if bri < ACTIVE_CHARACTER_THRESH
    ]
    found_active_character = len(active_character) == 1

    if found_active_character and active_character[0] + 1 != current_active_character:
        if current_activity.activity_type == ActivityType.LOADING:
            current_activity.activity_data = True

        current_active_character = active_character[0] + 1
        if current_characters[current_active_character - 1] != None:
            print(
                f'Switched active character to "{current_characters[current_active_character - 1].character_display_name}"'
            )

    if not found_active_character:
        current_active_character = 0

        if loop_count % 8 == 0 and (
            ps_window_thread_instance == None
            or not ps_window_thread_instance.is_alive()
        ):
            ps_window_thread_instance = threading.Thread(
                target=update_genshin_open_status,
                daemon=True,
            )
            ps_window_thread_instance.start()

    if found_active_character:
        domain_cooldown = 0  # reset anti-domain read cooldown

        if current_activity.is_idle():
            # Restore previous activity once an active character is detected.
            current_activity = prev_non_idle_activity

        # _____________________________________________________________________
        #
        # CAPTURE PARTY MEMBERS
        # _____________________________________________________________________

        if (
            loop_count % OCR_CHARNAMES_ONE_IN == 0
            or len([a for a in current_characters if a == None]) > 0
        ):
            try:
                charname_cap = [
                    np.array(ImageGrab.grab(bbox=NAMES_4P_COORD[i])) for i in range(4)
                ]
            except OSError:
                print(
                    "OSError: Cannot capture screen. Try running as admin if this issue persists."
                )
                time.sleep(100)
                continue

            # ([bbox top left, top right, bottom right, bottom left], text, confidence)
            char_results = [
                reader.readtext(
                    img,
                    allowlist=ALLOWLIST,
                )
                for img in charname_cap
            ]

            for character_index, result in enumerate(char_results):
                if len(result) > 0:
                    text = " ".join([word.strip() for word in [r[1] for r in result]])
                    avg_conf = sum([r[2] for r in result]) / len(result)

                    if avg_conf > NAME_CONF_THRESH:
                        if text.lower() in party_capture_cache:
                            if party_capture_cache[text.lower()] != None:
                                # use cache if available
                                cache_match = party_capture_cache[text.lower()]
                                current_characters[character_index] = cache_match
                        else:
                            # search through character list for matching name.
                            matched_character = [
                                c for c in CHARACTERS if c.search_str in text.lower()
                            ]
                            if len(matched_character) == 1 and (
                                current_characters[character_index] == None
                                or matched_character[0]
                                != current_characters[character_index]
                            ):
                                party_capture_cache[text.lower()] = matched_character[0]
                                current_characters[character_index] = matched_character[
                                    0
                                ]
                                print(
                                    f"Detected character {character_index + 1}: {matched_character[0].character_display_name}"
                                )
                            elif len(matched_character) == 0:
                                party_capture_cache[text.lower()] = None
                                print(f"WARN: couldn't find character with name {text}")
                            elif len(matched_character) > 1:
                                party_capture_cache[text.lower()] = None
                                print(
                                    f"ERROR: multiple characters matched with name {text}: "
                                    + f"{[c.character_display_name for c in matched_character]}"
                                )
                                print('Fix characters.csv.')

        # _____________________________________________________________________
        #
        # CAPTURE LOCATION
        # _____________________________________________________________________

        if loop_count % OCR_LOC_ONE_IN == 0:
            try:
                loc_cap = np.array(ImageGrab.grab(bbox=LOCATION_COORD))
            except OSError:
                print(
                    "OSError: Cannot capture screen. Try running as admin if this issue persists."
                )
                time.sleep(100)
                continue

            loc_results = reader.readtext(loc_cap, allowlist=ALLOWLIST)

            loc_text = " ".join(
                [
                    word.strip()
                    for word in [r[1] for r in loc_results if r[2] > LOC_CONF_THRESH]
                ]
            )
            if len(loc_text) > 0:
                if "mission accept" in loc_text.lower():
                    if current_activity.activity_type != ActivityType.COMMISSION:
                        current_activity = Activity(ActivityType.COMMISSION, None)
                        print(f"Detected doing commissions")

                elif loc_text.lower() in location_capture_cache:
                    if location_capture_cache[loc_text.lower()] != None:
                        # use cache if available
                        cache_match = location_capture_cache[loc_text.lower()]
                        if cache_match != None and (
                            current_activity.activity_type != ActivityType.LOCATION
                            or current_activity.activity_data.search_str
                            != cache_match.search_str
                        ):
                            current_activity = Activity(
                                ActivityType.LOCATION, cache_match
                            )
                            prev_location = cache_match
                            print(f"Detected location: {cache_match.location_name}")
                else:
                    location_match = [
                        l for l in LOCATIONS if l.search_str in loc_text.lower()
                    ]

                    # If more than one location match, just use the first one.
                    # (This can happen in the map)
                    if len(location_match) >= 1 and (
                        current_activity.activity_type != ActivityType.LOCATION
                        or current_activity.activity_data.search_str
                        != location_match[0].search_str
                    ):
                        if len(location_match) > 1:
                            print(
                                f"WARN: multiple locations matched with name {loc_text}: "
                                + f"{[l.location_name for l in location_match]}"
                            )
                            print(
                                f"Using first match: {location_match[0].location_name}"
                            )

                        location_capture_cache[loc_text.lower()] = location_match[0]
                        current_activity = Activity(
                            ActivityType.LOCATION, location_match[0]
                        )
                        prev_location = location_match[0]
                        print(f"Detected location: {location_match[0].location_name}")

                    elif len(location_match) == 0:
                        location_capture_cache[loc_text.lower()] = None
                        # print(f"WARN: couldn't find location with name {loc_text}")
                        # A lot of non-location text is expected to be captured in this box.
                    
                    if DEBUG_MODE:
                        loc = location_capture_cache[loc_text.lower()]
                        print(f'added "{loc_text.lower()}" = '+
                              f'"{loc and loc.location_name or None}" to location cache '
                              + f'({len(location_capture_cache)})')

        # _____________________________________________________________________
        #
        # CAPTURE BOSS
        # _____________________________________________________________________

        if loop_count % OCR_BOSS_ONE_IN == 0:
            try:
                boss_cap = np.array(ImageGrab.grab(bbox=BOSS_COORD))
            except OSError:
                print(
                    "OSError: Cannot capture screen. Try running as admin if this issue persists."
                )
                time.sleep(100)
                continue

            boss_results = reader.readtext(boss_cap, allowlist=ALLOWLIST)

            boss_text = " ".join(
                [
                    word.strip()
                    for word in [r[1] for r in boss_results if r[2] > LOC_CONF_THRESH]
                ]
            )
            if len(boss_text) > 0:
                if boss_text.lower() in world_boss_capture_cache:
                    if world_boss_capture_cache[boss_text.lower()] != None:
                        # use cache if available
                        cache_match = world_boss_capture_cache[boss_text.lower()]
                        if cache_match != None and (
                            current_activity.activity_type != ActivityType.WORLD_BOSS
                            or current_activity.activity_data.search_str
                            != cache_match.search_str
                        ):
                            current_activity = Activity(
                                ActivityType.WORLD_BOSS, cache_match
                            )
                            print(f"Detected boss: {cache_match.boss_name}")
                else:
                    boss_match = [
                        b for b in BOSSES if b.search_str in boss_text.lower()
                    ]

                    if len(boss_match) == 1 and (
                        current_activity.activity_type != ActivityType.WORLD_BOSS
                        or current_activity.activity_data.search_str
                        != boss_match[0].search_str
                    ):
                        world_boss_capture_cache[boss_text.lower()] = boss_match[0]
                        current_activity = Activity(
                            ActivityType.WORLD_BOSS, boss_match[0]
                        )
                        print(f"Detected boss: {boss_match[0].boss_name}")
                    elif len(boss_match) > 1:
                        world_boss_capture_cache[boss_text.lower()] = None
                        print(
                            f"WARN: multiple bosses matched with name {boss_text}: "
                            + f"{[b.boss_name for b in boss_match]}"
                        )
                    elif len(boss_match) == 0:
                        world_boss_capture_cache[boss_text.lower()] = None

    elif not found_active_character:
        curr_game_paused = True  # Set False later if domain/party setup detected.

        if domain_cooldown > 0:
            domain_cooldown -= 1

        # _____________________________________________________________________
        #
        # CAPTURE PARTY SETUP TEXT
        # _____________________________________________________________________

        try:
            party_cap = np.array(ImageGrab.grab(bbox=PARTY_SETUP_COORD))
        except OSError:
            print(
                "OSError: Cannot capture screen. Try running as admin if this issue persists."
            )
            time.sleep(100)
            continue

        party_results = reader.readtext(party_cap, allowlist=ALLOWLIST)

        party_text = " ".join(
            [
                word.strip()
                for word in [r[1] for r in party_results if r[2] > LOC_CONF_THRESH]
            ]
        )
        if "party setup" in party_text.lower():
            curr_game_paused = False
            domain_cooldown = PARTY_SETUP_DOMAIN_COOLDOWN
            if current_activity.activity_type != ActivityType.PARTY_SETUP:
                current_activity = Activity(
                    ActivityType.PARTY_SETUP, prev_non_idle_activity
                )
                print(f"Entered Party Setup")

        # _____________________________________________________________________
        #
        # CAPTURE DOMAIN
        # _____________________________________________________________________

        if domain_cooldown == 0:
            # Prevent capturing domain if in party setup,
            # otherwise 4th character's name will be captured as domain.
            try:
                domain_cap = np.array(ImageGrab.grab(bbox=DOMAIN_COORD))
            except OSError:
                print(
                    "OSError: Cannot capture screen. Try running as admin if this issue persists."
                )
                time.sleep(100)
                continue

            domain_results = reader.readtext(domain_cap, allowlist=ALLOWLIST)

            domain_text = " ".join(
                [
                    word.strip()
                    for word in [r[1] for r in domain_results if r[2] > LOC_CONF_THRESH]
                ]
            )
            if len(domain_text) > 0:
                domain_match = [
                    d for d in DOMAINS if d.search_str in domain_text.lower()
                ]

                if len(domain_match) == 1 and (
                    current_activity.activity_type != ActivityType.DOMAIN
                    or current_activity.activity_data.search_str
                    != domain_match[0].search_str
                ):
                    curr_game_paused = False
                    current_activity = Activity(ActivityType.DOMAIN, domain_match[0])
                    print(
                        f"Detected domain: {current_activity.activity_data.domain_name}"
                    )

    if game_pause_state_cooldown > 0:
        game_pause_state_cooldown -= 1

    if curr_game_paused != game_paused:
        game_pause_state_cooldown = PAUSE_STATE_COOLDOWN
        game_paused = curr_game_paused
    elif (
        game_pause_state_cooldown == 0
        and curr_game_paused != game_pause_state_displayed
    ):
        if curr_game_paused:
            current_activity = Activity(ActivityType.PAUSED, prev_non_idle_activity)
            print("Game paused.")
        else:
            print("Game resumed.")

        game_pause_state_displayed = curr_game_paused

    if not current_activity.is_idle():
        prev_non_idle_activity = current_activity

    if (
        current_activity.activity_type != ActivityType.LOADING
        or current_activity.activity_data
    ) and game_start_time == None:
        game_start_time = time.time()

    time.sleep(SLEEP_PER_ITERATION)  # 80 ms between reads
