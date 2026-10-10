# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot — MALZ CODEX Premium Dashboard
Embedded Async Web Server (aiohttp) — Single File Edition
UI: MALZ CODEX Edition — Premium Glass Theme
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web


# ============================================================
#  EXP TABLE + LEVEL CALCULATION
# ============================================================

EXP_TABLE: Dict[int, int] = {
    1: 0, 2: 48, 3: 202, 4: 544, 5: 1012, 6: 1844, 7: 2792, 8: 3800,
    9: 4870, 10: 6004, 11: 7192, 12: 8448, 13: 9760, 14: 11140, 15: 12566,
    16: 14060, 17: 15610, 18: 17224, 19: 18902, 20: 20632, 21: 22424, 22: 24278,
    23: 26192, 24: 28166, 25: 30200, 26: 32294, 27: 34448, 28: 37804, 29: 41274,
    30: 44870, 31: 48582, 32: 53394, 33: 58566, 34: 64096, 35: 69994, 36: 76460,
    37: 83506, 38: 91128, 39: 99322, 40: 108092, 41: 120144, 42: 133266, 43: 147472,
    44: 162760, 45: 179126, 46: 196572, 47: 215368, 48: 235516, 49: 257010, 50: 279860,
    51: 304056, 52: 348318, 53: 394982, 54: 444044, 55: 495508, 56: 549364, 57: 633756,
    58: 721744, 59: 813336, 60: 908522, 61: 1041438, 62: 1180352, 63: 1325266,
    64: 1476184, 65: 1634300, 66: 1840946, 67: 2056594, 68: 2281242, 69: 2514880,
    70: 2757530, 71: 3059506, 72: 3372284, 73: 3699456, 74: 4041030, 75: 4397002,
    76: 4829104, 77: 5282204, 78: 5756304, 79: 6251408, 80: 6776502, 81: 7381324,
    82: 8043154, 83: 8752982, 84: 9510808, 85: 10316338, 86: 11277190, 87: 12291748,
    88: 13360304, 89: 14482858, 90: 15659418, 91: 17026708, 92: 18453950, 93: 19941280,
    94: 21488570, 95: 23095858, 96: 24763138, 97: 26490428, 98: 28378704, 99: 30124996,
    100: 32032884
}


def calculate_level_progress(level: int, current_exp: int) -> Dict[str, Any]:
    level = max(1, level)
    next_level = min(100, level + 1)
    base_exp = EXP_TABLE.get(level, 0)
    target_exp = EXP_TABLE.get(next_level, base_exp + 50000)

    needed_for_level = max(1, target_exp - base_exp)
    earned_in_level = max(0, current_exp - base_exp)
    remaining_exp = max(0, target_exp - current_exp)
    progress_pct = min(100.0, max(0.0, (earned_in_level / needed_for_level) * 100.0))

    return {
        "next_level": next_level,
        "base_exp": base_exp,
        "target_exp": target_exp,
        "needed_for_level": needed_for_level,
        "earned_in_level": earned_in_level,
        "remaining_exp": remaining_exp,
        "progress_pct": round(progress_pct, 1)
    }


# ============================================================
#  BOT STATE
# ============================================================

class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 200
        self.total_matches = 0
        self.total_gained_exp = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.account_token_map: Dict[str, str] = {}
        self.auth_to_game_id: Dict[str, str] = {}
        self.game_to_auth_id: Dict[str, str] = {}
        self.paused_accounts: set = set()
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self.active_writers: Dict[str, set] = {}

    def register_writer(self, uid: str, writer):
        uid_str = str(uid)
        if uid_str not in self.active_writers:
            self.active_writers[uid_str] = set()
        self.active_writers[uid_str].add(writer)

    def unregister_writer(self, uid: str, writer):
        uid_str = str(uid)
        if uid_str in self.active_writers:
            self.active_writers[uid_str].discard(writer)
            if not self.active_writers[uid_str]:
                self.active_writers.pop(uid_str, None)

    def close_writers_for_account(self, uid: str):
        uid_str = str(uid)
        candidates = {uid_str}
        if uid_str in self.auth_to_game_id:
            candidates.add(str(self.auth_to_game_id[uid_str]))
        if uid_str in self.game_to_auth_id:
            candidates.add(str(self.game_to_auth_id[uid_str]))
        if uid_str in self.account_token_map:
            mapped = self.account_token_map[uid_str]
            candidates.add(str(mapped))
            candidates.add(str(mapped)[:16])

        for c in list(candidates):
            writers = list(self.active_writers.get(c, []))
            for w in writers:
                try:
                    if hasattr(w, "close"):
                        if hasattr(w, "is_closing"):
                            if not w.is_closing():
                                w.close()
                        else:
                            w.close()
                except Exception:
                    pass
            self.active_writers.pop(c, None)

    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": str(uid) if uid else None
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    def register_account(self, uid: str, nickname: str, region: str, level: int, exp: int,
                         likes: int = 0, token: Optional[str] = None, auth_uid: Optional[str] = None):
        uid_str = str(uid)
        auth_uid_str = str(auth_uid) if auth_uid else self.game_to_auth_id.get(uid_str, "")
        if auth_uid_str:
            self.auth_to_game_id[auth_uid_str] = uid_str
            self.game_to_auth_id[uid_str] = auth_uid_str
            self.account_token_map[auth_uid_str] = uid_str
            self.account_token_map[uid_str] = auth_uid_str
        if token:
            self.account_token_map[uid_str] = token
            self.account_token_map[token[:16]] = uid_str
            if auth_uid_str:
                self.account_token_map[auth_uid_str] = token

        prog = calculate_level_progress(level or 1, exp)

        lvl_val = level or 1
        acc_mode = "BR" if lvl_val < 3 else "LONE_WOLF"
        acc_mode_label = "Battle Royale (Lvl < 3)" if lvl_val < 3 else "Lone Wolf (Lvl 3+)"

        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "auth_uid": auth_uid_str or "",
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "BD",
                "level": lvl_val,
                "next_level": prog["next_level"],
                "mode": acc_mode,
                "mode_label": acc_mode_label,
                "initial_exp": exp,
                "current_exp": exp,
                "gained_exp": 0,
                "remaining_exp": prog["remaining_exp"],
                "target_exp": prog["target_exp"],
                "needed_for_level": prog["needed_for_level"],
                "earned_in_level": prog["earned_in_level"],
                "progress_pct": prog["progress_pct"],
                "likes": likes or 0,
                "status": "PAUSED" if self.is_paused(uid_str) else "ONLINE",
                "matches_played": 0,
                "active_matches": 0,
                "last_match_time": None,
                "token": token or "",
                "start_time": time.time(),
                "is_paused": self.is_paused(uid_str),
                "paused_at": time.time() if self.is_paused(uid_str) else None,
                "total_pause_duration": 0.0,
                "last_updated": time.strftime("%H:%M:%S")
            }
        else:
            acc = self.accounts[uid_str]
            if auth_uid_str:
                acc["auth_uid"] = auth_uid_str
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level:
                acc["level"] = level
            if token:
                acc["token"] = token
            acc["current_exp"] = exp
            acc["gained_exp"] = max(0, exp - acc["initial_exp"])
            acc["next_level"] = prog["next_level"]
            acc["remaining_exp"] = prog["remaining_exp"]
            acc["target_exp"] = prog["target_exp"]
            acc["needed_for_level"] = prog["needed_for_level"]
            acc["earned_in_level"] = prog["earned_in_level"]
            acc["progress_pct"] = prog["progress_pct"]
            acc["likes"] = likes
            if not acc.get("is_paused"):
                acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def get_account_uptime(self, uid_str: str) -> int:
        acc = self.accounts.get(uid_str)
        if not acc:
            mapped = self.game_to_auth_id.get(uid_str) or self.auth_to_game_id.get(uid_str)
            if mapped and mapped in self.accounts:
                acc = self.accounts[mapped]
        if not acc:
            return 0
        start_t = acc.get("start_time", time.time())
        total_pause = acc.get("total_pause_duration", 0.0)
        if acc.get("is_paused") and acc.get("paused_at"):
            return max(0, int(acc["paused_at"] - start_t - total_pause))
        return max(0, int(time.time() - start_t - total_pause))

    def is_paused(self, uid: str) -> bool:
        uid_str = str(uid)
        if uid_str in self.paused_accounts:
            return True
        game_id = self.auth_to_game_id.get(uid_str)
        if game_id and game_id in self.paused_accounts:
            return True
        auth_uid = self.game_to_auth_id.get(uid_str)
        if auth_uid and auth_uid in self.paused_accounts:
            return True
        acc = self.accounts.get(uid_str) or (self.accounts.get(game_id) if game_id else None)
        if acc and acc.get("is_paused"):
            return True
        return False

    def toggle_pause(self, uid: str) -> bool:
        uid_str = str(uid)
        candidates = {uid_str}
        if uid_str in self.auth_to_game_id:
            candidates.add(self.auth_to_game_id[uid_str])
        if uid_str in self.game_to_auth_id:
            candidates.add(self.game_to_auth_id[uid_str])

        target_acc = None
        target_key = uid_str
        for c in candidates:
            if c in self.accounts:
                target_acc = self.accounts[c]
                target_key = c
                break

        is_now_paused = not self.is_paused(uid_str)
        if is_now_paused:
            for c in candidates:
                self.paused_accounts.add(c)
                self.close_writers_for_account(c)
            if target_acc:
                target_acc["is_paused"] = True
                target_acc["paused_at"] = time.time()
                target_acc["status"] = "PAUSED"
            nick = target_acc.get("nickname", target_key) if target_acc else target_key
            self.log(f"⏸ UID {target_key} ({nick}) matchmaking PAUSED (TCP socket disconnected).", "warning", target_key)
            if "on_pause_toggle" in self.refresh_callbacks:
                try:
                    asyncio.create_task(self.refresh_callbacks["on_pause_toggle"](target_key, True))
                except Exception:
                    pass
        else:
            for c in candidates:
                self.paused_accounts.discard(c)
            if target_acc:
                target_acc["is_paused"] = False
                if target_acc.get("paused_at"):
                    pause_dur = time.time() - target_acc["paused_at"]
                    target_acc["total_pause_duration"] = target_acc.get("total_pause_duration", 0.0) + pause_dur
                    target_acc["paused_at"] = None
                target_acc["status"] = "ONLINE"
            nick = target_acc.get("nickname", target_key) if target_acc else target_key
            self.log(f"▶ UID {target_key} ({nick}) matchmaking RESUMED.", "success", target_key)
            if "on_pause_toggle" in self.refresh_callbacks:
                try:
                    asyncio.create_task(self.refresh_callbacks["on_pause_toggle"](target_key, False))
                except Exception:
                    pass

        return is_now_paused

    def toggle_pause_all(self) -> bool:
        any_active = any(not self.is_paused(k) for k in self.accounts.keys())
        for k in list(self.accounts.keys()):
            current_paused = self.is_paused(k)
            if any_active and not current_paused:
                self.toggle_pause(k)
            elif not any_active and current_paused:
                self.toggle_pause(k)
        return any_active

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            old_exp = acc["current_exp"]
            old_level = acc.get("level", 1)
            acc["current_exp"] = current_exp
            if level is not None and level > 0:
                acc["level"] = level
            acc["gained_exp"] = max(0, current_exp - acc["initial_exp"])

            current_lvl = acc["level"]
            acc["mode"] = "BR" if current_lvl < 3 else "LONE_WOLF"
            acc["mode_label"] = "Battle Royale (Lvl < 3)" if current_lvl < 3 else "Lone Wolf (Lvl 3+)"

            prog = calculate_level_progress(acc["level"], current_exp)
            acc["next_level"] = prog["next_level"]
            acc["remaining_exp"] = prog["remaining_exp"]
            acc["target_exp"] = prog["target_exp"]
            acc["needed_for_level"] = prog["needed_for_level"]
            acc["earned_in_level"] = prog["earned_in_level"]
            acc["progress_pct"] = prog["progress_pct"]
            acc["last_updated"] = time.strftime("%H:%M:%S")

            if old_level < 3 and current_lvl >= 3:
                self.log(
                    f"🎉 LEVEL UP! UID {uid_str} ({acc['nickname']}) reached Level {current_lvl}! Switching from Battle Royale to Lone Wolf mode!",
                    "success",
                    uid_str
                )

            diff = current_exp - old_exp
            if diff > 0:
                self.log(
                    f"★ UID {uid_str} ({acc['nickname']}) gained +{diff:,} EXP | Level {acc['level']} [{acc['mode']}] ({prog['progress_pct']}% - {prog['remaining_exp']:,} EXP to Lvl {prog['next_level']})",
                    "success",
                    uid_str
                )
            self.recalc_totals()

    def get_account_level(self, uid: str) -> int:
        uid_str = str(uid)
        acc = self.accounts.get(uid_str)
        if not acc:
            mapped = self.game_to_auth_id.get(uid_str) or self.auth_to_game_id.get(uid_str)
            if mapped and mapped in self.accounts:
                acc = self.accounts[mapped]
        if acc:
            return int(acc.get("level", 1) or 1)
        return 1

    def get_account_mode(self, uid: str) -> str:
        lvl = self.get_account_level(uid)
        return "BR" if lvl < 3 else "LONE_WOLF"

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            self.accounts[uid_str]["status"] = status
            if active_matches is not None:
                self.accounts[uid_str]["active_matches"] = active_matches
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            self.accounts[uid_str]["matches_played"] += 1
            self.accounts[uid_str]["last_match_time"] = time.strftime("%H:%M:%S")
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")
            self.log(f"⚔ Match #{self.accounts[uid_str]['matches_played']} finished for {self.accounts[uid_str]['nickname']} ({uid_str})", "info", uid_str)

    def recalc_totals(self):
        self.total_gained_exp = sum(acc.get("gained_exp", 0) for acc in self.accounts.values())


bot_state = BotState()


# ============================================================
#  EMBEDDED HTML DASHBOARD — MALZ CODEX PREMIUM EDITION
# ============================================================

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>MALZ CODEX — FreeFire Level Up Command Center</title>

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css">

<style>
:root {
    --bg-0: #050308;
    --bg-1: #0a0715;
    --bg-2: #100a24;
    --card: rgba(17, 12, 38, 0.72);
    --card-2: rgba(24, 17, 52, 0.85);
    --card-hi: rgba(35, 24, 72, 0.92);

    --stroke: rgba(148, 88, 233, 0.14);
    --stroke-2: rgba(148, 88, 233, 0.28);
    --stroke-hi: rgba(0, 255, 200, 0.42);

    --c1: #00ffc8;
    --c2: #00b3ff;
    --c3: #a855f7;
    --c4: #ec4899;
    --c5: #ff9f1c;
    --c6: #ff2e63;

    --txt: #f5f7ff;
    --txt-2: #b4bcd9;
    --txt-3: #7a82a8;
    --txt-4: #4d547a;

    --glow-c1: 0 0 32px rgba(0, 255, 200, 0.28);
    --glow-c3: 0 0 32px rgba(168, 85, 247, 0.32);
    --shadow: 0 20px 60px -12px rgba(0, 0, 0, 0.85);

    --r-xl: 22px;
    --r-lg: 16px;
    --r-md: 12px;
    --r-sm: 8px;
}

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-family: 'Plus Jakarta Sans', sans-serif;
    -webkit-tap-highlight-color: transparent;
}

html, body { height: 100%; }

body {
    background-color: var(--bg-0);
    background-image:
        radial-gradient(ellipse 60% 45% at 12% 8%, rgba(168, 85, 247, 0.22) 0%, transparent 55%),
        radial-gradient(ellipse 55% 40% at 88% 92%, rgba(0, 255, 200, 0.16) 0%, transparent 55%),
        radial-gradient(ellipse 50% 55% at 50% 50%, rgba(0, 179, 255, 0.08) 0%, transparent 65%),
        linear-gradient(180deg, #050308 0%, #0a0715 40%, #0e0a20 100%);
    background-attachment: fixed;
    color: var(--txt);
    min-height: 100vh;
    overflow-x: hidden;
    font-size: 15px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(rgba(148, 88, 233, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0, 255, 200, 0.03) 1px, transparent 1px);
    background-size: 52px 52px;
    pointer-events: none;
    z-index: 0;
    mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
    -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 80%);
}

::selection { background: rgba(0, 255, 200, 0.3); color: #fff; }

.shell {
    position: relative;
    z-index: 1;
    max-width: 1600px;
    margin: 0 auto;
    padding: 22px;
}

/* ============ TOP STATUS RIBBON ============ */
.ribbon {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 18px;
    padding: 8px 18px;
    margin-bottom: 18px;
    background: linear-gradient(90deg,
        rgba(168, 85, 247, 0.06) 0%,
        rgba(0, 255, 200, 0.08) 50%,
        rgba(168, 85, 247, 0.06) 100%);
    border: 1px solid var(--stroke);
    border-radius: 100px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.4px;
    text-transform: uppercase;
    color: var(--txt-2);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    flex-wrap: wrap;
}
.ribbon span { display: inline-flex; align-items: center; gap: 6px; }
.ribbon .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--c1); box-shadow: 0 0 8px var(--c1); animation: blink 1.4s infinite; }
.ribbon .sep { width: 4px; height: 4px; border-radius: 50%; background: var(--txt-4); }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* ============ TOP HEADER ============ */
.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 18px 24px;
    background: linear-gradient(135deg, rgba(20, 14, 44, 0.85) 0%, rgba(14, 10, 32, 0.92) 100%);
    border: 1px solid var(--stroke-2);
    border-radius: var(--r-xl);
    backdrop-filter: blur(24px) saturate(140%);
    -webkit-backdrop-filter: blur(24px) saturate(140%);
    box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    margin-bottom: 22px;
    position: relative;
    overflow: hidden;
}
.topbar::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0, 255, 200, 0.6), rgba(168, 85, 247, 0.6), transparent);
}

.brand { display: flex; align-items: center; gap: 16px; }

.avatar {
    width: 58px;
    height: 58px;
    border-radius: 18px;
    position: relative;
    background: linear-gradient(135deg, var(--c3), var(--c2), var(--c1));
    padding: 2px;
    box-shadow: 0 0 24px rgba(168, 85, 247, 0.55), 0 0 40px rgba(0, 255, 200, 0.25);
    flex-shrink: 0;
}
.avatar img {
    width: 100%;
    height: 100%;
    border-radius: 16px;
    object-fit: cover;
    display: block;
    background: #0d0920;
}
.avatar::after {
    content: '';
    position: absolute;
    bottom: -3px; right: -3px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--c1);
    border: 3px solid #0d0920;
    box-shadow: 0 0 12px var(--c1);
    animation: pulse-dot 2s infinite;
}
@keyframes pulse-dot {
    0%, 100% { transform: scale(1); opacity: 1; }
    50% { transform: scale(1.15); opacity: 0.85; }
}

.brand-meta h1 {
    font-size: 24px;
    font-weight: 900;
    letter-spacing: -0.8px;
    line-height: 1.1;
    background: linear-gradient(90deg, #ffffff 0%, #c8b3ff 40%, #00ffc8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.brand-meta h1 .tag {
    font-size: 12px;
    font-weight: 700;
    color: var(--txt-3);
    letter-spacing: 1.5px;
    text-transform: uppercase;
    -webkit-text-fill-color: var(--txt-3);
    margin-left: 8px;
    vertical-align: middle;
}
.brand-meta .sub {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 4px;
    flex-wrap: wrap;
}
.chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.6px;
    text-transform: uppercase;
}
.chip-live {
    background: rgba(0, 255, 200, 0.1);
    border: 1px solid rgba(0, 255, 200, 0.35);
    color: var(--c1);
}
.chip-ver {
    background: rgba(168, 85, 247, 0.12);
    border: 1px solid rgba(168, 85, 247, 0.35);
    color: #d8b4fe;
}
.chip-meta {
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.08);
    color: var(--txt-3);
}

.pulse-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--c1);
    box-shadow: 0 0 8px var(--c1);
    position: relative;
}
.pulse-dot::after {
    content: '';
    position: absolute;
    inset: -4px;
    border-radius: 50%;
    border: 2px solid var(--c1);
    animation: ring 1.8s ease-out infinite;
}
@keyframes ring {
    0% { transform: scale(0.5); opacity: 1; }
    100% { transform: scale(2.4); opacity: 0; }
}

.topbar-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

/* ============ BUTTONS ============ */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 10px 18px;
    border-radius: var(--r-md);
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    border: 1px solid transparent;
    outline: none;
    user-select: none;
    letter-spacing: 0.2px;
    transition: transform 0.16s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.22s ease, background 0.22s ease, border-color 0.22s ease, color 0.2s ease;
    white-space: nowrap;
}
.btn:active { transform: scale(0.93); }

.btn-primary {
    background: linear-gradient(135deg, #a855f7 0%, #00b3ff 50%, #00ffc8 100%);
    color: #06121a;
    font-weight: 900;
    box-shadow: 0 6px 22px rgba(168, 85, 247, 0.42), 0 6px 18px rgba(0, 255, 200, 0.22);
    position: relative;
    overflow: hidden;
}
.btn-primary::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg, transparent 30%, rgba(255, 255, 255, 0.45) 50%, transparent 70%);
    transform: translateX(-100%);
    transition: transform 0.6s ease;
}
.btn-primary:hover { transform: translateY(-2px); }
.btn-primary:hover::after { transform: translateX(100%); }

.btn-ghost {
    background: rgba(255, 255, 255, 0.04);
    border-color: var(--stroke-2);
    color: var(--txt);
}
.btn-ghost:hover {
    background: rgba(168, 85, 247, 0.12);
    border-color: var(--stroke-hi);
    color: #fff;
}

.btn-icon {
    width: 40px;
    height: 40px;
    padding: 0;
    border-radius: var(--r-md);
    background: rgba(168, 85, 247, 0.08);
    border: 1px solid var(--stroke-2);
    color: var(--txt-2);
}
.btn-icon:hover {
    background: rgba(0, 255, 200, 0.14);
    border-color: var(--c1);
    color: var(--c1);
    transform: translateY(-1px);
}
.btn-icon:active { transform: scale(0.86); }
.btn-icon i { transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1); }
.btn-icon:active i { transform: scale(1.2); }

/* ============ STATS STRIP ============ */
.stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 22px;
}
.stat {
    background: linear-gradient(140deg, rgba(20, 14, 44, 0.8) 0%, rgba(12, 9, 28, 0.85) 100%);
    border: 1px solid var(--stroke);
    border-radius: var(--r-lg);
    padding: 18px 20px;
    backdrop-filter: blur(18px);
    -webkit-backdrop-filter: blur(18px);
    box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.03);
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: relative;
    overflow: hidden;
    cursor: pointer;
    transition: transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.24s ease, box-shadow 0.24s ease;
}
.stat::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px;
    height: 100%;
    background: var(--accent, var(--c1));
    box-shadow: 0 0 12px var(--accent, var(--c1));
}
.stat::after {
    content: '';
    position: absolute;
    top: 0; right: 0;
    width: 140px; height: 140px;
    background: radial-gradient(circle, var(--accent, var(--c1)), transparent 70%);
    opacity: 0.06;
    border-radius: 50%;
    transform: translate(40%, -40%);
    pointer-events: none;
}
.stat:hover {
    transform: translateY(-3px);
    border-color: var(--stroke-hi);
    box-shadow: var(--shadow), var(--glow-c1);
}
.stat:active { transform: translateY(-1px) scale(0.985); }

.stat h3 {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    color: var(--txt-3);
    margin-bottom: 8px;
}
.stat .value {
    font-size: 28px;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -1.2px;
    color: #fff;
    line-height: 1;
}
.stat .sub {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-top: 8px;
    font-size: 11px;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 20px;
    background: rgba(0, 255, 200, 0.1);
    color: var(--c1);
    border: 1px solid rgba(0, 255, 200, 0.25);
}
.stat .sub.purple { background: rgba(168, 85, 247, 0.12); color: #d8b4fe; border-color: rgba(168, 85, 247, 0.35); }
.stat .sub.amber { background: rgba(255, 159, 28, 0.12); color: #ffb84d; border-color: rgba(255, 159, 28, 0.35); }

.stat .ico {
    width: 52px; height: 52px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
    background: rgba(0, 255, 200, 0.12);
    color: var(--c1);
    border: 1px solid rgba(0, 255, 200, 0.22);
    transition: transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.stat:hover .ico { transform: scale(1.08) rotate(-4deg); }

/* ============ WORKSPACE ============ */
.workspace {
    display: grid;
    grid-template-columns: 1fr 500px;
    gap: 22px;
    align-items: start;
}

.panel {
    background: linear-gradient(160deg, rgba(18, 12, 40, 0.82) 0%, rgba(12, 9, 28, 0.88) 100%);
    border: 1px solid var(--stroke);
    border-radius: var(--r-xl);
    padding: 20px;
    backdrop-filter: blur(20px) saturate(130%);
    -webkit-backdrop-filter: blur(20px) saturate(130%);
    box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.03);
    display: flex;
    flex-direction: column;
    position: relative;
    overflow: hidden;
}
.panel::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0, 255, 200, 0.35), rgba(168, 85, 247, 0.35), transparent);
}

.panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 18px;
    padding-bottom: 14px;
    border-bottom: 1px solid var(--stroke);
    flex-wrap: wrap;
}
.panel-title { display: flex; align-items: center; gap: 12px; }
.panel-title h2 { font-size: 17px; font-weight: 800; color: #fff; letter-spacing: -0.3px; }
.panel-title .pill {
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 800;
    font-family: 'JetBrains Mono', monospace;
    background: rgba(0, 255, 200, 0.12);
    color: var(--c1);
    border: 1px solid rgba(0, 255, 200, 0.28);
}
.panel-title .panel-ico {
    width: 34px; height: 34px;
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 15px;
    background: linear-gradient(135deg, rgba(168, 85, 247, 0.18), rgba(0, 255, 200, 0.14));
    border: 1px solid var(--stroke-2);
    color: var(--c1);
}

/* ============ FILTER ROW ============ */
.filters {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    margin-bottom: 16px;
    flex-wrap: wrap;
}
.search {
    flex: 1;
    min-width: 220px;
    position: relative;
}
.search i {
    position: absolute;
    left: 14px; top: 50%;
    transform: translateY(-50%);
    color: var(--txt-4);
    font-size: 13px;
    transition: color 0.22s ease, transform 0.22s ease;
}
.search:focus-within i { color: var(--c1); transform: translateY(-50%) scale(1.15); }
.search input {
    width: 100%;
    background: rgba(255, 255, 255, 0.035);
    border: 1px solid var(--stroke);
    border-radius: var(--r-md);
    padding: 10px 14px 10px 40px;
    color: #fff;
    font-size: 13px;
    outline: none;
    transition: all 0.22s ease;
    font-family: inherit;
}
.search input::placeholder { color: var(--txt-4); }
.search input:focus {
    border-color: rgba(0, 255, 200, 0.5);
    background: rgba(0, 255, 200, 0.06);
    box-shadow: 0 0 0 4px rgba(0, 255, 200, 0.08);
    transform: scale(1.01);
}

.tabs {
    display: flex;
    gap: 4px;
    padding: 4px;
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid var(--stroke);
    border-radius: var(--r-md);
}
.tab {
    padding: 7px 12px;
    border-radius: 8px;
    background: transparent;
    border: none;
    color: var(--txt-3);
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.2s ease;
    font-family: inherit;
    letter-spacing: 0.2px;
}
.tab:hover { color: var(--txt); }
.tab.active {
    background: rgba(0, 255, 200, 0.14);
    color: var(--c1);
    border: 1px solid rgba(0, 255, 200, 0.32);
    box-shadow: 0 0 12px rgba(0, 255, 200, 0.18);
}
.tab:active { transform: scale(0.94); }

/* ============ ACCOUNT CARDS ============ */
.acc-list {
    display: flex;
    flex-direction: column;
    gap: 14px;
    max-height: 700px;
    overflow-y: auto;
    padding-right: 4px;
    scrollbar-width: thin;
    scrollbar-color: rgba(168, 85, 247, 0.3) transparent;
}
.acc-list::-webkit-scrollbar { width: 6px; }
.acc-list::-webkit-scrollbar-track { background: transparent; }
.acc-list::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, var(--c3), var(--c1));
    border-radius: 4px;
}

.acc {
    background: linear-gradient(150deg, rgba(20, 14, 44, 0.75) 0%, rgba(12, 9, 28, 0.85) 100%);
    border: 1px solid var(--stroke);
    border-radius: var(--r-lg);
    padding: 18px;
    position: relative;
    transition: transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.24s ease, background 0.24s ease, box-shadow 0.24s ease;
    overflow: hidden;
}
.acc::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--c1), var(--c3), var(--c2));
    opacity: 0.6;
}
.acc:hover {
    transform: translateY(-3px);
    border-color: var(--stroke-hi);
    background: linear-gradient(150deg, rgba(30, 20, 62, 0.82) 0%, rgba(16, 12, 36, 0.9) 100%);
    box-shadow: var(--shadow), var(--glow-c1);
}
.acc:active { transform: translateY(-1px) scale(0.995); }

.acc-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 14px;
}
.acc-id { display: flex; gap: 12px; align-items: center; flex: 1; min-width: 0; }

.acc-ava {
    width: 46px; height: 46px;
    border-radius: 13px;
    background: linear-gradient(135deg, #1a1240, #2a1a5f);
    border: 1px solid rgba(0, 255, 200, 0.32);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--c1);
    font-size: 18px;
    position: relative;
    flex-shrink: 0;
    transition: transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.24s ease;
}
.acc:hover .acc-ava {
    transform: scale(1.06);
    box-shadow: 0 0 16px rgba(0, 255, 200, 0.4);
}
.acc-ava .lv {
    position: absolute;
    bottom: -6px; right: -6px;
    background: linear-gradient(135deg, var(--c3), var(--c1));
    color: #06121a;
    font-size: 9px;
    font-weight: 900;
    padding: 2px 6px;
    border-radius: 7px;
    border: 2px solid #0d0920;
    font-family: 'JetBrains Mono', monospace;
    box-shadow: 0 0 10px rgba(0, 255, 200, 0.4);
}

.acc-name {
    font-size: 15px;
    font-weight: 800;
    color: #fff;
    display: flex;
    align-items: center;
    gap: 7px;
    flex-wrap: wrap;
    line-height: 1.3;
    letter-spacing: -0.2px;
}
.badge-region {
    background: rgba(0, 179, 255, 0.14);
    color: #7dd3fc;
    border: 1px solid rgba(0, 179, 255, 0.35);
    padding: 1px 7px;
    border-radius: 5px;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.5px;
}
.badge-mode {
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: 0.4px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}
.badge-mode.br {
    background: rgba(255, 159, 28, 0.13);
    color: #ffb84d;
    border: 1px solid rgba(255, 159, 28, 0.4);
}
.badge-mode.lw {
    background: rgba(168, 85, 247, 0.15);
    color: #d8b4fe;
    border: 1px solid rgba(168, 85, 247, 0.4);
}

.acc-sub {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-top: 4px;
    flex-wrap: wrap;
}
.acc-uid {
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    color: var(--txt-3);
    font-weight: 500;
}
.copy-btn {
    background: transparent;
    border: none;
    color: var(--txt-4);
    cursor: pointer;
    padding: 3px 5px;
    border-radius: 5px;
    font-size: 10px;
    transition: all 0.16s ease;
}
.copy-btn:hover { color: var(--c1); background: rgba(0, 255, 200, 0.1); }
.copy-btn:active { transform: scale(0.75); }

.uptime {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
    padding: 2px 8px;
    border-radius: 7px;
    color: var(--c1);
    background: rgba(0, 255, 200, 0.09);
    border: 1px solid rgba(0, 255, 200, 0.26);
    letter-spacing: 0.2px;
}
.uptime.paused {
    color: #ffb84d;
    background: rgba(255, 159, 28, 0.09);
    border-color: rgba(255, 159, 28, 0.3);
}

.status {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    flex-shrink: 0;
    white-space: nowrap;
}
.status .pulse-dot { width: 6px; height: 6px; }
.status.online {
    background: rgba(0, 255, 200, 0.11);
    color: var(--c1);
    border: 1px solid rgba(0, 255, 200, 0.34);
}
.status.online .pulse-dot { background: var(--c1); box-shadow: 0 0 8px var(--c1); }
.status.online .pulse-dot::after { border-color: var(--c1); }

.status.in_match {
    background: rgba(168, 85, 247, 0.14);
    color: #d8b4fe;
    border: 1px solid rgba(168, 85, 247, 0.5);
    animation: match-glow 1.8s infinite alternate;
}
.status.in_match .pulse-dot { background: #d8b4fe; box-shadow: 0 0 8px #d8b4fe; }
.status.in_match .pulse-dot::after { border-color: #d8b4fe; }
@keyframes match-glow {
    0% { box-shadow: 0 0 4px rgba(168, 85, 247, 0.3); }
    100% { box-shadow: 0 0 18px rgba(168, 85, 247, 0.6); }
}

.status.searching {
    background: rgba(0, 179, 255, 0.13);
    color: #7dd3fc;
    border: 1px solid rgba(0, 179, 255, 0.4);
}
.status.searching .pulse-dot { background: #7dd3fc; box-shadow: 0 0 8px #7dd3fc; }
.status.searching .pulse-dot::after { border-color: #7dd3fc; }

.status.paused {
    background: rgba(255, 159, 28, 0.11);
    color: #ffb84d;
    border: 1px solid rgba(255, 159, 28, 0.4);
}
.status.paused .pulse-dot { background: #ffb84d; box-shadow: 0 0 8px #ffb84d; }
.status.paused .pulse-dot::after { border-color: #ffb84d; animation: none; opacity: 0.3; }

.status.error, .status.offline {
    background: rgba(255, 46, 99, 0.11);
    color: #ff5c8a;
    border: 1px solid rgba(255, 46, 99, 0.34);
}
.status.error .pulse-dot, .status.offline .pulse-dot { background: #ff5c8a; box-shadow: 0 0 8px #ff5c8a; }
.status.error .pulse-dot::after, .status.offline .pulse-dot::after { border-color: #ff5c8a; animation: none; opacity: 0.3; }

/* ============ EXP GRID ============ */
.exp-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    background: rgba(0, 0, 0, 0.32);
    border: 1px solid var(--stroke);
    border-radius: var(--r-md);
    padding: 12px;
    margin-bottom: 12px;
}
.exp-cell {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
}
.exp-cell .lbl {
    font-size: 9px;
    color: var(--txt-4);
    text-transform: uppercase;
    font-weight: 800;
    letter-spacing: 0.8px;
}
.exp-cell .val {
    font-size: 13px;
    font-weight: 700;
    color: #fff;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: -0.3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.exp-cell .val.gain {
    color: var(--c1);
    text-shadow: 0 0 12px rgba(0, 255, 200, 0.5);
}

/* ============ PROGRESS ============ */
.prog {
    background: rgba(0, 0, 0, 0.24);
    border: 1px solid var(--stroke);
    border-radius: var(--r-md);
    padding: 12px 14px;
    margin-bottom: 12px;
    transition: border-color 0.24s ease, background 0.24s ease;
}
.prog:hover { border-color: rgba(0, 255, 200, 0.28); background: rgba(0, 255, 200, 0.03); }

.prog-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 9px;
    gap: 8px;
    flex-wrap: wrap;
}
.prog-lv {
    font-size: 11px;
    font-weight: 700;
    color: var(--txt-2);
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.prog-lv strong { color: var(--c1); font-family: 'JetBrains Mono', monospace; font-weight: 800; }

.prog-need {
    font-size: 10px;
    font-weight: 800;
    padding: 3px 9px;
    border-radius: 20px;
    background: linear-gradient(135deg, rgba(168, 85, 247, 0.18), rgba(0, 179, 255, 0.14));
    color: #d8b4fe;
    border: 1px solid rgba(168, 85, 247, 0.4);
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-family: 'JetBrains Mono', monospace;
    box-shadow: 0 0 12px rgba(168, 85, 247, 0.2);
    animation: need-pulse 2.6s ease-in-out infinite;
}
@keyframes need-pulse {
    0%, 100% { box-shadow: 0 0 10px rgba(168, 85, 247, 0.2); }
    50% { box-shadow: 0 0 18px rgba(168, 85, 247, 0.5); }
}

.prog-track {
    height: 10px;
    background: rgba(0, 0, 0, 0.6);
    border-radius: 20px;
    overflow: hidden;
    position: relative;
    border: 1px solid rgba(148, 88, 233, 0.18);
    box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.7);
}
.prog-fill {
    height: 100%;
    border-radius: 20px;
    background: linear-gradient(90deg, #00b3ff 0%, #00ffc8 30%, #a855f7 60%, #00ffc8 90%, #00b3ff 100%);
    background-size: 220% 100%;
    animation: shift 3.4s linear infinite;
    position: relative;
    transition: width 0.9s cubic-bezier(0.34, 1.56, 0.64, 1);
    box-shadow: 0 0 14px rgba(0, 255, 200, 0.55), 0 0 24px rgba(168, 85, 247, 0.28);
}
.prog-fill::before {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255, 255, 255, 0.7) 50%, transparent 100%);
    background-size: 200% 100%;
    animation: shimmer 2.4s infinite linear;
    border-radius: 20px;
}
.prog-fill::after {
    content: '';
    position: absolute;
    top: 1px; right: 1px; bottom: 1px;
    width: 4px;
    background: #fff;
    border-radius: 50%;
    box-shadow: 0 0 8px #fff, 0 0 16px var(--c1);
}
@keyframes shift {
    0% { background-position: 0% 50%; }
    100% { background-position: 200% 50%; }
}
@keyframes shimmer {
    0% { transform: translateX(-150%); }
    100% { transform: translateX(150%); }
}

.prog-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 7px;
    font-size: 10px;
    color: var(--txt-4);
    font-family: 'JetBrains Mono', monospace;
    font-weight: 600;
}
.prog-foot .pct {
    font-weight: 800;
    color: var(--c1);
    background: rgba(0, 255, 200, 0.1);
    border: 1px solid rgba(0, 255, 200, 0.28);
    padding: 1px 7px;
    border-radius: 8px;
    font-size: 10px;
}

/* ============ FOOTER / ACTIONS ============ */
.acc-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding-top: 12px;
    border-top: 1px solid var(--stroke);
    font-size: 11px;
    color: var(--txt-3);
    flex-wrap: wrap;
}
.acc-foot .last {
    font-family: 'JetBrains Mono', monospace;
    font-weight: 500;
}
.acc-actions { display: flex; align-items: center; gap: 6px; }
.act {
    width: 32px; height: 32px;
    border-radius: 9px;
    background: rgba(148, 88, 233, 0.08);
    border: 1px solid var(--stroke-2);
    color: var(--txt-3);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-size: 12px;
    transition: all 0.18s ease;
}
.act:hover {
    background: rgba(0, 255, 200, 0.14);
    color: var(--c1);
    border-color: var(--c1);
    transform: translateY(-1px);
}
.act:active { transform: scale(0.86) rotate(4deg); }
.act.pause { color: #ffb84d; }
.act.pause:hover { background: rgba(255, 159, 28, 0.18); color: #ffb84d; border-color: #ffb84d; }
.act.resume {
    background: rgba(0, 255, 200, 0.14);
    color: var(--c1);
    border-color: rgba(0, 255, 200, 0.42);
}
.act.resume:hover { background: rgba(0, 255, 200, 0.26); color: #fff; }
.act.danger:hover {
    background: rgba(255, 46, 99, 0.16);
    color: #ff5c8a;
    border-color: #ff5c8a;
}

/* ============ EMPTY STATE ============ */
.empty {
    text-align: center;
    padding: 60px 20px;
    color: var(--txt-3);
}
.empty i {
    font-size: 54px;
    margin-bottom: 16px;
    background: linear-gradient(135deg, var(--c3), var(--c1));
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    opacity: 0.75;
}
.empty p { font-size: 14px; color: var(--txt-2); margin-bottom: 18px; }

/* ============ CONSOLE ============ */
.console-panel { height: 820px; }
.console-tools {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 12px;
    flex-wrap: wrap;
}
.pills { display: flex; gap: 5px; flex-wrap: wrap; }
.pill-btn {
    padding: 5px 11px;
    border-radius: 8px;
    background: rgba(148, 88, 233, 0.06);
    border: 1px solid var(--stroke-2);
    color: var(--txt-3);
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.2s ease;
    font-family: inherit;
}
.pill-btn:hover { color: var(--txt); border-color: var(--stroke-hi); }
.pill-btn.active {
    background: rgba(0, 255, 200, 0.14);
    color: var(--c1);
    border-color: rgba(0, 255, 200, 0.4);
    box-shadow: 0 0 12px rgba(0, 255, 200, 0.18);
}
.pill-btn:active { transform: scale(0.92); }

.stream {
    flex: 1;
    background: linear-gradient(180deg, #05030c 0%, #08060f 100%);
    border: 1px solid var(--stroke);
    border-radius: var(--r-md);
    padding: 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
    position: relative;
    scrollbar-width: thin;
    scrollbar-color: rgba(168, 85, 247, 0.35) transparent;
}
.stream::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0, 255, 200, 0.35), transparent);
}
.stream::-webkit-scrollbar { width: 6px; }
.stream::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, var(--c3), var(--c1));
    border-radius: 3px;
}

.log-line {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    line-height: 1.55;
    animation: slide-in 0.26s cubic-bezier(0.34, 1.56, 0.64, 1);
    word-break: break-word;
}
@keyframes slide-in {
    0% { opacity: 0; transform: translateX(-10px); }
    100% { opacity: 1; transform: translateX(0); }
}
.log-line .ts {
    color: var(--txt-4);
    flex-shrink: 0;
    font-size: 11px;
    font-weight: 500;
}
.log-line .msg { flex: 1; font-weight: 500; }
.log-line .msg.info { color: #7dd3fc; }
.log-line .msg.success { color: var(--c1); text-shadow: 0 0 12px rgba(0, 255, 200, 0.35); }
.log-line .msg.warning { color: #ffb84d; }
.log-line .msg.error { color: #ff5c8a; text-shadow: 0 0 10px rgba(255, 92, 138, 0.35); }

.jump {
    position: absolute;
    bottom: 14px;
    right: 16px;
    padding: 7px 14px;
    border-radius: 20px;
    background: rgba(0, 255, 200, 0.18);
    border: 1px solid var(--c1);
    color: #fff;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    backdrop-filter: blur(10px);
    display: none;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.5);
    transition: all 0.2s ease;
}
.jump:hover { background: var(--c1); color: #06121a; transform: translateY(-2px); }
.jump:active { transform: scale(0.92); }

/* ============ MODAL ============ */
.overlay {
    position: fixed;
    inset: 0;
    background: rgba(4, 2, 12, 0.85);
    backdrop-filter: blur(14px) saturate(120%);
    -webkit-backdrop-filter: blur(14px) saturate(120%);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 100;
    padding: 20px;
}
.overlay.on { display: flex; }

.modal {
    background: linear-gradient(160deg, #100a26 0%, #0a0718 100%);
    border: 1px solid var(--stroke-2);
    border-radius: var(--r-xl);
    width: 100%;
    max-width: 500px;
    padding: 26px;
    box-shadow: 0 30px 80px rgba(0, 0, 0, 0.85), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    animation: pop 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
    position: relative;
    overflow: hidden;
}
.modal::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0, 255, 200, 0.6), rgba(168, 85, 247, 0.6), transparent);
}
@keyframes pop {
    0% { transform: scale(0.9) translateY(20px); opacity: 0; }
    100% { transform: scale(1) translateY(0); opacity: 1; }
}

.modal-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 22px;
}
.modal-head h3 {
    font-size: 18px;
    font-weight: 800;
    display: flex;
    align-items: center;
    gap: 10px;
    color: #fff;
}
.modal-head h3 i {
    width: 36px; height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, rgba(168, 85, 247, 0.2), rgba(0, 255, 200, 0.16));
    border: 1px solid var(--stroke-2);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--c1);
    font-size: 15px;
}

.field { margin-bottom: 18px; }
.field label {
    display: block;
    font-size: 12px;
    font-weight: 700;
    color: var(--txt-2);
    margin-bottom: 7px;
    letter-spacing: 0.3px;
    text-transform: uppercase;
}
.field input, .field select, .field textarea {
    width: 100%;
    background: rgba(148, 88, 233, 0.06);
    border: 1px solid var(--stroke-2);
    border-radius: var(--r-md);
    padding: 12px 15px;
    color: #fff;
    font-size: 14px;
    outline: none;
    font-family: inherit;
    transition: all 0.22s ease;
    resize: vertical;
}
.field input::placeholder, .field textarea::placeholder { color: var(--txt-4); }
.field input:focus, .field select:focus, .field textarea:focus {
    border-color: rgba(0, 255, 200, 0.55);
    background: rgba(0, 255, 200, 0.06);
    box-shadow: 0 0 0 4px rgba(0, 255, 200, 0.08);
    transform: scale(1.01);
}
.field select option { background: #100a26; color: #fff; }

.modal-foot {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 22px;
}

/* ============ TOAST ============ */
.toasts {
    position: fixed;
    top: 22px;
    right: 22px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: 10px;
    pointer-events: none;
}
.toast {
    background: rgba(16, 10, 38, 0.95);
    border: 1px solid var(--stroke-2);
    border-radius: var(--r-md);
    padding: 12px 18px;
    color: #fff;
    font-size: 13px;
    font-weight: 600;
    backdrop-filter: blur(14px);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.55);
    display: flex;
    align-items: center;
    gap: 10px;
    pointer-events: auto;
    animation: toast-in 0.32s cubic-bezier(0.34, 1.56, 0.64, 1);
    max-width: 380px;
}
@keyframes toast-in {
    0% { transform: translateX(60px); opacity: 0; }
    100% { transform: translateX(0); opacity: 1; }
}
.toast i { font-size: 16px; }
.toast.success { border-color: rgba(0, 255, 200, 0.55); }
.toast.success i { color: var(--c1); }
.toast.error { border-color: rgba(255, 46, 99, 0.55); }
.toast.error i { color: #ff5c8a; }
.toast.info { border-color: rgba(0, 179, 255, 0.55); }
.toast.info i { color: #7dd3fc; }
.toast.warning { border-color: rgba(255, 159, 28, 0.55); }
.toast.warning i { color: #ffb84d; }

/* ============ DEVELOPER CARD IN MODAL ============ */
.dev-hero {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 16px;
    border-radius: var(--r-lg);
    background: linear-gradient(135deg, rgba(168, 85, 247, 0.12), rgba(0, 255, 200, 0.08));
    border: 1px solid var(--stroke-2);
    margin-bottom: 18px;
}
.dev-hero img {
    width: 62px; height: 62px;
    border-radius: 16px;
    object-fit: cover;
    border: 2px solid rgba(0, 255, 200, 0.4);
    box-shadow: 0 0 20px rgba(0, 255, 200, 0.32);
    flex-shrink: 0;
}
.dev-hero .meta { min-width: 0; }
.dev-hero .meta h3 {
    font-size: 17px;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.3px;
    background: linear-gradient(90deg, #fff, #00ffc8);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
.dev-hero .meta p {
    font-size: 12px;
    color: var(--txt-3);
    margin-top: 3px;
    font-weight: 600;
    letter-spacing: 0.3px;
}

.dev-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.dev-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 11px 14px;
    border-radius: var(--r-md);
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid var(--stroke);
    transition: all 0.22s ease;
    text-decoration: none;
    color: inherit;
}
.dev-item:hover {
    background: rgba(148, 88, 233, 0.1);
    border-color: var(--stroke-hi);
    transform: translateX(4px);
}
.dev-item .ico {
    width: 34px; height: 34px;
    border-radius: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 15px;
    background: linear-gradient(135deg, rgba(168, 85, 247, 0.2), rgba(0, 255, 200, 0.14));
    border: 1px solid var(--stroke-2);
    color: var(--c1);
    flex-shrink: 0;
}
.dev-item .info { flex: 1; min-width: 0; }
.dev-item .info .key {
    font-size: 10px;
    font-weight: 800;
    color: var(--txt-4);
    text-transform: uppercase;
    letter-spacing: 1px;
}
.dev-item .info .val {
    font-size: 13px;
    font-weight: 700;
    color: #fff;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.dev-item .arrow { color: var(--txt-4); font-size: 12px; transition: all 0.22s ease; }
.dev-item:hover .arrow { color: var(--c1); transform: translateX(4px); }

.dev-foot {
    margin-top: 18px;
    text-align: center;
    font-size: 11px;
    color: var(--txt-3);
    font-weight: 600;
    letter-spacing: 0.4px;
    padding-top: 14px;
    border-top: 1px solid var(--stroke);
}
.dev-foot strong {
    background: linear-gradient(90deg, var(--c3), var(--c1));
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 800;
}

/* ============ MOBILE ============ */
.mobile-bar { display: none; }
.bottom-nav { display: none; }

@media (max-width: 1100px) {
    .workspace { grid-template-columns: 1fr; }
    .console-panel { height: 520px; }
}

@media (max-width: 860px) {
    .stats { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 720px) {
    body { padding-bottom: 88px; }
    .shell { padding: 12px; }
    .ribbon { display: none; }
    .topbar { display: none; }

    .mobile-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 14px;
        background: linear-gradient(135deg, rgba(20, 14, 44, 0.9), rgba(14, 10, 32, 0.95));
        border: 1px solid var(--stroke-2);
        border-radius: var(--r-lg);
        backdrop-filter: blur(20px) saturate(140%);
        -webkit-backdrop-filter: blur(20px) saturate(140%);
        margin-bottom: 12px;
        position: sticky;
        top: 8px;
        z-index: 50;
        box-shadow: var(--shadow);
    }
    .mobile-bar .brand { gap: 10px; }
    .mobile-bar .avatar {
        width: 40px; height: 40px;
        border-radius: 12px;
    }
    .mobile-bar .avatar img { border-radius: 10px; }
    .mobile-bar .avatar::after {
        width: 12px; height: 12px;
        border-width: 2px;
    }
    .mobile-bar h2 {
        font-size: 15px;
        font-weight: 900;
        background: linear-gradient(90deg, #fff, var(--c1));
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.3px;
    }
    .mobile-bar .mini-sub {
        font-size: 9px;
        color: var(--c1);
        font-weight: 800;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-top: 1px;
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }
    .mobile-bar .mini-sub .pulse-dot { width: 5px; height: 5px; }

    .stats { grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
    .stat { padding: 14px; border-radius: var(--r-md); }
    .stat .value { font-size: 20px; }
    .stat h3 { font-size: 10px; }
    .stat .ico { width: 38px; height: 38px; font-size: 15px; }

    .panel { padding: 14px; border-radius: var(--r-lg); }
    .console-panel { height: calc(100vh - 220px); }

    .mobile-view { display: none; }
    .mobile-view.active { display: flex; flex-direction: column; }

    .bottom-nav {
        position: fixed;
        bottom: 0; left: 0; right: 0;
        height: 72px;
        background: linear-gradient(180deg, rgba(10, 7, 21, 0.9), rgba(6, 4, 14, 0.98));
        border-top: 1px solid var(--stroke-2);
        backdrop-filter: blur(24px) saturate(140%);
        -webkit-backdrop-filter: blur(24px) saturate(140%);
        display: flex;
        align-items: center;
        justify-content: space-around;
        z-index: 90;
        padding: 0 8px;
        box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.5);
    }
    .nav-item {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 3px;
        background: none;
        border: none;
        color: var(--txt-4);
        font-size: 10px;
        font-weight: 700;
        cursor: pointer;
        padding: 8px 14px;
        border-radius: 12px;
        flex: 1;
        max-width: 100px;
        transition: all 0.24s cubic-bezier(0.34, 1.56, 0.64, 1);
        font-family: inherit;
        letter-spacing: 0.3px;
    }
    .nav-item i { font-size: 17px; transition: transform 0.24s cubic-bezier(0.34, 1.56, 0.64, 1); }
    .nav-item:active { transform: scale(0.9); }
    .nav-item:active i { transform: scale(1.3) translateY(-2px); }
    .nav-item.active {
        color: var(--c1);
        background: rgba(0, 255, 200, 0.12);
    }
    .nav-item.active i { transform: scale(1.15); filter: drop-shadow(0 0 6px var(--c1)); }

    .overlay { align-items: flex-end; padding: 0; }
    .modal {
        max-width: 100%;
        border-radius: 24px 24px 0 0;
        padding: 22px 18px 34px 18px;
        animation: sheet-up 0.36s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    @keyframes sheet-up {
        0% { transform: translateY(100%); }
        100% { transform: translateY(0); }
    }

    .toasts { top: 12px; left: 12px; right: 12px; }
    .toast { max-width: 100%; }
}

@media (max-width: 420px) {
    .exp-grid { padding: 10px; gap: 6px; }
    .exp-cell .val { font-size: 11px; }
    .exp-cell .lbl { font-size: 8px; }
}
</style>
</head>
<body>

<div class="toasts" id="toasts"></div>

<div class="shell">

    <!-- ============ STATUS RIBBON ============ -->
    <div class="ribbon">
        <span><span class="dot"></span> SYSTEM LIVE</span>
        <span class="sep"></span>
        <span><i class="fa-solid fa-bolt" style="color:var(--c1)"></i> ULTRA SMOOTH TCP GATEWAY</span>
        <span class="sep"></span>
        <span><i class="fa-solid fa-shield-halved" style="color:var(--c3)"></i> OB55 PARALLEL ENGINE</span>
        <span class="sep"></span>
        <span><i class="fa-solid fa-code" style="color:var(--c2)"></i> BY MALZ CODEX</span>
    </div>

    <!-- ============ DESKTOP TOPBAR ============ -->
    <header class="topbar">
        <div class="brand">
            <div class="avatar" onclick="openDevModal()" title="MALZ CODEX">
                <img src="https://cdn.phototourl.com/member/2026-10-07-da0318ae-9d20-47d8-82b4-0bc72973e9b0.png" alt="MALZ CODEX" onerror="this.style.display='none'">
            </div>
            <div class="brand-meta">
                <h1>MALZ CODEX <span class="tag">| LEVEL UP BOT</span></h1>
                <div class="sub">
                    <span class="chip chip-live"><span class="pulse-dot"></span> LIVE</span>
                    <span class="chip chip-ver">v3.0 PREMIUM</span>
                    <span class="chip chip-meta">OB55 ENGINE</span>
                </div>
            </div>
        </div>

        <div class="topbar-actions">
            <button class="btn btn-ghost" onclick="openDevModal()">
                <i class="fa-solid fa-user-astronaut"></i> Developer
            </button>
            <button class="btn btn-icon" onclick="manualRefresh()" title="Refresh"><i class="fa-solid fa-rotate"></i></button>
            <button class="btn btn-primary" onclick="openAddModal()">
                <i class="fa-solid fa-plus"></i> Add Account
            </button>
        </div>
    </header>

    <!-- ============ MOBILE TOP BAR ============ -->
    <div class="mobile-bar">
        <div class="brand">
            <div class="avatar" onclick="openDevModal()">
                <img src="https://cdn.phototourl.com/member/2026-10-07-da0318ae-9d20-47d8-82b4-0bc72973e9b0.png" alt="MALZ" onerror="this.style.display='none'">
            </div>
            <div>
                <h2>MALZ CODEX</h2>
                <span class="mini-sub"><span class="pulse-dot"></span> OB55 LIVE</span>
            </div>
        </div>
        <div style="display:flex; gap:7px;">
            <button class="btn btn-icon" onclick="manualRefresh()" title="Refresh" style="width:36px;height:36px;"><i class="fa-solid fa-rotate" style="font-size:12px;"></i></button>
            <button class="btn btn-primary" style="padding:8px 12px;font-size:12px;" onclick="openAddModal()"><i class="fa-solid fa-plus"></i> Add</button>
        </div>
    </div>

    <!-- ============ STATS STRIP ============ -->
    <div class="stats">
        <div class="stat" style="--accent: var(--c1);">
            <div>
                <h3>Active Accounts</h3>
                <div class="value" id="s-accounts">0</div>
                <div class="sub" id="s-online"><i class="fa-solid fa-circle-check"></i> 0 Online</div>
            </div>
            <div class="ico"><i class="fa-solid fa-users"></i></div>
        </div>

        <div class="stat" style="--accent: var(--c1);">
            <div>
                <h3>Total EXP Gained</h3>
                <div class="value" id="s-exp" style="color:var(--c1)">+0</div>
                <div class="sub" id="s-rate"><i class="fa-solid fa-gauge-high"></i> ~0 EXP/hr</div>
            </div>
            <div class="ico"><i class="fa-solid fa-angles-up"></i></div>
        </div>

        <div class="stat" style="--accent: var(--c3);">
            <div>
                <h3>Matches Completed</h3>
                <div class="value" id="s-matches">0</div>
                <div class="sub purple" id="s-active"><i class="fa-solid fa-gamepad"></i> 0 In Match</div>
            </div>
            <div class="ico" style="background:rgba(168,85,247,0.14); color:#d8b4fe; border-color:rgba(168,85,247,0.28);"><i class="fa-solid fa-trophy"></i></div>
        </div>

        <div class="stat" style="--accent: var(--c5);">
            <div>
                <h3>Bot Uptime</h3>
                <div class="value" id="s-uptime" style="font-size:24px;">00:00:00</div>
                <div class="sub amber"><i class="fa-solid fa-shield-halved"></i> 100% Online</div>
            </div>
            <div class="ico" style="background:rgba(255,159,28,0.14); color:#ffb84d; border-color:rgba(255,159,28,0.28);"><i class="fa-solid fa-clock"></i></div>
        </div>
    </div>

    <!-- ============ WORKSPACE ============ -->
    <div class="workspace">

        <!-- ACCOUNTS PANEL -->
        <div class="panel mobile-view active" id="view-accounts">
            <div class="panel-head">
                <div class="panel-title">
                    <div class="panel-ico"><i class="fa-solid fa-user-astronaut"></i></div>
                    <h2>Accounts & EXP Tracker</h2>
                    <span class="pill" id="acc-count">0 Active</span>
                </div>
                <button class="btn btn-ghost" id="btn-pause-all" onclick="togglePauseAll()" style="padding:8px 14px;font-size:12px;">
                    <i class="fa-solid fa-pause"></i> <span>Pause All</span>
                </button>
            </div>

            <div class="filters">
                <div class="search">
                    <i class="fa-solid fa-magnifying-glass"></i>
                    <input type="text" id="acc-search" placeholder="Cari Nickname atau UID..." oninput="filterAccounts()">
                </div>
                <div class="tabs">
                    <button class="tab active" data-f="all" onclick="setFilter('all', this)">All</button>
                    <button class="tab" data-f="in_match" onclick="setFilter('in_match', this)">In Match</button>
                    <button class="tab" data-f="online" onclick="setFilter('online', this)">Online</button>
                    <button class="tab" data-f="paused" onclick="setFilter('paused', this)">Paused</button>
                </div>
            </div>

            <div class="acc-list" id="acc-list">
                <div class="empty">
                    <i class="fa-solid fa-circle-notch fa-spin"></i>
                    <p>Connecting to Bot Core...</p>
                </div>
            </div>
        </div>

        <!-- CONSOLE PANEL -->
        <div class="panel console-panel mobile-view" id="view-console">
            <div class="panel-head">
                <div class="panel-title">
                    <div class="panel-ico" style="background:linear-gradient(135deg,rgba(0,255,200,0.2),rgba(0,179,255,0.16)); color:var(--c1);"><i class="fa-solid fa-terminal"></i></div>
                    <h2>Live Match Console</h2>
                </div>
                <button class="btn btn-icon" onclick="clearLogs()" title="Clear"><i class="fa-solid fa-trash-can" style="font-size:12px;"></i></button>
            </div>

            <div class="console-tools">
                <div class="pills">
                    <button class="pill-btn active" onclick="setLogFilter('all', this)">All</button>
                    <button class="pill-btn" onclick="setLogFilter('match', this)">Matches</button>
                    <button class="pill-btn" onclick="setLogFilter('success', this)">EXP Gained</button>
                    <button class="pill-btn" onclick="setLogFilter('error', this)">Errors</button>
                </div>
                <button class="pill-btn active" id="btn-autoscroll" onclick="toggleAutoScroll()">
                    <i class="fa-solid fa-arrows-down-to-line"></i> Auto
                </button>
            </div>

            <div class="stream" id="stream" onscroll="handleScroll()"></div>
            <button class="jump" id="jump" onclick="jumpBottom()"><i class="fa-solid fa-arrow-down"></i> Latest</button>
        </div>

        <!-- STATS PANEL (MOBILE) -->
        <div class="panel mobile-view" id="view-stats">
            <div class="panel-head">
                <div class="panel-title">
                    <div class="panel-ico" style="background:linear-gradient(135deg,rgba(168,85,247,0.22),rgba(0,255,200,0.14)); color:#d8b4fe;"><i class="fa-solid fa-chart-line"></i></div>
                    <h2>Performance Analytics</h2>
                </div>
            </div>

            <div style="display:grid; grid-template-columns:1fr; gap:12px;">
                <div class="stat" style="--accent:var(--c1); cursor:default;">
                    <div>
                        <h3>Engine Speed</h3>
                        <div class="value" id="m-rate" style="font-size:22px; color:var(--c1);">~0 EXP/hr</div>
                        <div class="sub">Safe Multi-Match UDP injection rate</div>
                    </div>
                    <div class="ico"><i class="fa-solid fa-gauge-high"></i></div>
                </div>

                <div class="stat" style="--accent:var(--c3); cursor:default;">
                    <div>
                        <h3>Total Matches Logged</h3>
                        <div class="value" id="m-matches" style="font-size:22px; color:#d8b4fe;">0</div>
                        <div class="sub purple">Completed sessions</div>
                    </div>
                    <div class="ico" style="background:rgba(168,85,247,0.14); color:#d8b4fe; border-color:rgba(168,85,247,0.28);"><i class="fa-solid fa-trophy"></i></div>
                </div>

                <div class="stat" style="--accent:var(--c1); cursor:default;">
                    <div>
                        <h3>System Health</h3>
                        <div class="value" style="font-size:16px; color:var(--c1);"><i class="fa-solid fa-shield-halved"></i> 100% Operational</div>
                        <div class="sub">Cloudflare DNS + Persistent Device ID</div>
                    </div>
                    <div class="ico"><i class="fa-solid fa-heart-pulse"></i></div>
                </div>

                <div class="stat" style="--accent:var(--c2); cursor:pointer;" onclick="openDevModal()">
                    <div>
                        <h3>Developed By</h3>
                        <div class="value" style="font-size:20px; background:linear-gradient(90deg,#fff,#00ffc8);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;">MALZ CODEX</div>
                        <div class="sub"><i class="fa-solid fa-code"></i> Tap untuk info developer</div>
                    </div>
                    <div class="ico" style="background:rgba(0,179,255,0.14); color:#7dd3fc; border-color:rgba(0,179,255,0.28);"><i class="fa-solid fa-user-astronaut"></i></div>
                </div>
            </div>
        </div>

    </div>
</div>

<!-- ============ MOBILE BOTTOM NAV ============ -->
<nav class="bottom-nav">
    <button class="nav-item active" onclick="switchTab('accounts', this)">
        <i class="fa-solid fa-user-group"></i>
        <span>Accounts</span>
    </button>
    <button class="nav-item" onclick="switchTab('stats', this)">
        <i class="fa-solid fa-chart-pie"></i>
        <span>Stats</span>
    </button>
    <button class="nav-item" onclick="switchTab('console', this)">
        <i class="fa-solid fa-terminal"></i>
        <span>Console</span>
    </button>
    <button class="nav-item" onclick="openAddModal()">
        <i class="fa-solid fa-circle-plus" style="color:var(--c1)"></i>
        <span>Add</span>
    </button>
</nav>

<!-- ============ ADD ACCOUNT MODAL ============ -->
<div class="overlay" id="add-modal">
    <div class="modal">
        <div class="modal-head">
            <h3><i class="fa-solid fa-user-plus"></i> Add New Account</h3>
            <button class="btn btn-icon" onclick="closeAddModal()" style="width:36px;height:36px;"><i class="fa-solid fa-xmark" style="font-size:13px;"></i></button>
        </div>
        <form id="add-form" onsubmit="submitAdd(event)">
            <div class="field">
                <label>Login Type</label>
                <select id="acc-type" onchange="toggleForm()">
                    <option value="guest">Guest Account (UID + Password)</option>
                    <option value="token">Access Token</option>
                </select>
            </div>
            <div id="guest-fields">
                <div class="field">
                    <label>Guest UID</label>
                    <input type="text" id="acc-uid" placeholder="e.g. 7872038363" autocomplete="off">
                </div>
                <div class="field">
                    <label>Guest Password / Key</label>
                    <input type="text" id="acc-pwd" placeholder="e.g. 381002140664..." autocomplete="off">
                </div>
            </div>
            <div id="token-fields" style="display:none;">
                <div class="field">
                    <label>Access Token</label>
                    <textarea id="acc-token" rows="3" placeholder="Paste access token here..."></textarea>
                </div>
            </div>
            <div class="modal-foot">
                <button type="button" class="btn btn-ghost" onclick="closeAddModal()">Cancel</button>
                <button type="submit" class="btn btn-primary"><i class="fa-solid fa-plus"></i> Save & Start</button>
            </div>
        </form>
    </div>
</div>

<!-- ============ DEVELOPER MODAL ============ -->
<div class="overlay" id="dev-modal">
    <div class="modal">
        <div class="modal-head">
            <h3><i class="fa-solid fa-code"></i> Developer Info</h3>
            <button class="btn btn-icon" onclick="closeDevModal()" style="width:36px;height:36px;"><i class="fa-solid fa-xmark" style="font-size:13px;"></i></button>
        </div>

        <div class="dev-hero">
            <img src="https://cdn.phototourl.com/member/2026-10-07-da0318ae-9d20-47d8-82b4-0bc72973e9b0.png" alt="MALZ CODEX" onerror="this.style.display='none'">
            <div class="meta">
                <h3>MALZ CODEX</h3>
                <p>FreeFire Bot Developer • Premium Engine Builder</p>
            </div>
        </div>

        <div class="dev-list">
            <a class="dev-item" href="https://tiktok.com/@malzwithyou" target="_blank" rel="noopener">
                <div class="ico"><i class="fa-brands fa-tiktok"></i></div>
                <div class="info">
                    <div class="key">TikTok</div>
                    <div class="val">@malzwithyou</div>
                </div>
                <i class="fa-solid fa-arrow-right arrow"></i>
            </a>
            <a class="dev-item" href="https://youtube.com/@Nikmal_hsb" target="_blank" rel="noopener">
                <div class="ico"><i class="fa-brands fa-youtube"></i></div>
                <div class="info">
                    <div class="key">YouTube</div>
                    <div class="val">@Nikmal_hsb</div>
                </div>
                <i class="fa-solid fa-arrow-right arrow"></i>
            </a>
            <a class="dev-item" href="https://github.com/ini_nikmal" target="_blank" rel="noopener">
                <div class="ico"><i class="fa-brands fa-github"></i></div>
                <div class="info">
                    <div class="key">GitHub</div>
                    <div class="val">@ini_nikmal</div>
                </div>
                <i class="fa-solid fa-arrow-right arrow"></i>
            </a>
            <a class="dev-item" href="https://t.me/malzwithyou" target="_blank" rel="noopener">
                <div class="ico"><i class="fa-brands fa-telegram"></i></div>
                <div class="info">
                    <div class="key">Telegram</div>
                    <div class="val">@malzwithyou</div>
                </div>
                <i class="fa-solid fa-arrow-right arrow"></i>
            </a>
        </div>

        <div class="dev-foot">
            Built with <strong>MALZ CODEX</strong> Engine • v3.0 Premium
        </div>
    </div>
</div>

<script>
const EXP_TABLE = {
    1:0,2:48,3:202,4:544,5:1012,6:1844,7:2792,8:3800,9:4870,10:6004,11:7192,12:8448,
    13:9760,14:11140,15:12566,16:14060,17:15610,18:17224,19:18902,20:20632,21:22424,22:24278,
    23:26192,24:28166,25:30200,26:32294,27:34448,28:37804,29:41274,30:44870,31:48582,32:53394,
    33:58566,34:64096,35:69994,36:76460,37:83506,38:91128,39:99322,40:108092,41:120144,42:133266,
    43:147472,44:162760,45:179126,46:196572,47:215368,48:235516,49:257010,50:279860,51:304056,
    52:348318,53:394982,54:444044,55:495508,56:549364,57:633756,58:721744,59:813336,60:908522,
    61:1041438,62:1180352,63:1325266,64:1476184,65:1634300,66:1840946,67:2056594,68:2281242,
    69:2514880,70:2757530,71:3059506,72:3372284,73:3699456,74:4041030,75:4397002,76:4829104,
    77:5282204,78:5756304,79:6251408,80:6776502,81:7381324,82:8043154,83:8752982,84:9510808,
    85:10316338,86:11277190,87:12291748,88:13360304,89:14482858,90:15659418,91:17026708,
    92:18453950,93:19941280,94:21488570,95:23095858,96:24763138,97:26490428,98:28378704,
    99:30124996,100:32032884
};

let cacheAcc = [];
let cacheLogs = [];
let autoScroll = true;
let filter = 'all';
let logFilter = 'all';
let clientTime = Date.now();

function esc(t) {
    if (t === null || t === undefined) return '';
    return String(t)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function toast(msg, type = 'info') {
    const c = document.getElementById('toasts');
    const t = document.createElement('div');
    t.className = 'toast ' + type;
    const icons = {
        success: 'fa-circle-check',
        error: 'fa-triangle-exclamation',
        info: 'fa-circle-info',
        warning: 'fa-triangle-exclamation'
    };
    t.innerHTML = `<i class="fa-solid ${icons[type] || icons.info}"></i> <span>${esc(msg)}</span>`;
    c.appendChild(t);
    setTimeout(() => {
        t.style.transition = 'all 0.3s ease';
        t.style.opacity = '0';
        t.style.transform = 'translateX(60px)';
        setTimeout(() => t.remove(), 300);
    }, 3200);
}

function openAddModal() { document.getElementById('add-modal').classList.add('on'); }
function closeAddModal() { document.getElementById('add-modal').classList.remove('on'); }
function openDevModal() { document.getElementById('dev-modal').classList.add('on'); }
function closeDevModal() { document.getElementById('dev-modal').classList.remove('on'); }

function toggleForm() {
    const t = document.getElementById('acc-type').value;
    document.getElementById('guest-fields').style.display = t === 'guest' ? 'block' : 'none';
    document.getElementById('token-fields').style.display = t === 'token' ? 'block' : 'none';
}

async function submitAdd(e) {
    e.preventDefault();
    const type = document.getElementById('acc-type').value;
    let payload = {};
    if (type === 'guest') {
        const uid = document.getElementById('acc-uid').value.trim();
        const pwd = document.getElementById('acc-pwd').value.trim();
        if (!uid || !pwd) return toast('UID dan Password wajib diisi', 'error');
        payload = { uid, password: pwd };
    } else {
        const token = document.getElementById('acc-token').value.trim();
        if (!token) return toast('Access token wajib diisi', 'error');
        payload = { token };
    }
    try {
        const res = await fetch('/api/account/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.status === 'ok') {
            closeAddModal();
            document.getElementById('add-form').reset();
            toggleForm();
            toast('Account added and worker scheduled!', 'success');
            fetchStats();
        } else {
            toast('Gagal: ' + (data.error || 'Unknown'), 'error');
        }
    } catch (err) {
        toast('Network error adding account', 'error');
    }
}

async function delAccount(uid, authUid = '') {
    if (!confirm(`Hapus permanen akun UID ${uid}?`)) return;
    try {
        const res = await fetch('/api/account/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uid, auth_uid: authUid })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            toast(`Account ${uid} removed.`, 'info');
            const card = document.getElementById('card-' + uid);
            if (card) card.remove();
            fetchStats();
        } else {
            toast('Error: ' + (data.error || 'Unknown'), 'error');
        }
    } catch (err) {
        toast('Network error deleting', 'error');
    }
}

async function refreshAcc(uid) {
    try {
        toast(`Refreshing profile ${uid}...`, 'info');
        await fetch('/api/account/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uid })
        });
        setTimeout(fetchStats, 1000);
    } catch (err) {
        toast('Failed to refresh', 'error');
    }
}

async function restartAcc(uid) {
    try {
        toast(`Restarting worker ${uid}...`, 'info');
        await fetch('/api/account/restart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uid })
        });
        setTimeout(fetchStats, 1000);
    } catch (err) {
        toast('Failed to restart', 'error');
    }
}

async function clearLogs() {
    try {
        await fetch('/api/logs/clear', { method: 'POST' });
        cacheLogs = [];
        document.getElementById('stream').innerHTML = '';
        toast('Console cleared.', 'info');
    } catch (err) {
        toast('Failed to clear logs', 'error');
    }
}

function copyUid(uid) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(uid).then(() => toast(`Copied: ${uid}`, 'success')).catch(() => toast(`UID: ${uid}`, 'info'));
    } else {
        toast(`UID: ${uid}`, 'info');
    }
}

function manualRefresh() {
    fetchStats();
    toast('Stats refreshed', 'info');
}

function setFilter(f, btn) {
    filter = f;
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    filterAccounts();
}

function fmtDur(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
    return `${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
}

async function togglePause(uid) {
    try {
        const res = await fetch('/api/account/pause', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uid })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            toast(data.is_paused ? `Paused: ${uid}` : `Resumed: ${uid}`, data.is_paused ? 'warning' : 'success');
            fetchStats();
        } else {
            toast(data.error || 'Failed', 'error');
        }
    } catch (err) {
        toast('Network error toggling pause', 'error');
    }
}

async function togglePauseAll() {
    try {
        const res = await fetch('/api/account/pause_all', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            toast(data.all_paused ? 'All accounts PAUSED' : 'All accounts RESUMED', data.all_paused ? 'warning' : 'success');
            fetchStats();
        } else {
            toast(data.error || 'Failed', 'error');
        }
    } catch (err) {
        toast('Network error', 'error');
    }
}

function filterAccounts() {
    const q = (document.getElementById('acc-search').value || '').toLowerCase().trim();
    document.querySelectorAll('.acc').forEach(card => {
        const uid = (card.dataset.uid || '').toLowerCase();
        const nick = (card.dataset.nick || '').toLowerCase();
        const st = (card.dataset.status || '').toLowerCase();
        const paused = card.dataset.paused === '1';

        const mq = !q || uid.includes(q) || nick.includes(q);
        let mf = true;
        if (filter === 'in_match') mf = (st.includes('in_match') || st.includes('match')) && !paused;
        else if (filter === 'online') mf = (st.includes('online') || st.includes('searching')) && !paused;
        else if (filter === 'paused') mf = paused || st.includes('paused');

        card.style.display = (mq && mf) ? 'block' : 'none';
    });
}

function switchTab(name, btn) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    document.querySelectorAll('.mobile-view').forEach(v => v.classList.remove('active'));
    const el = document.getElementById('view-' + name);
    if (el) el.classList.add('active');
    if (name === 'console' && autoScroll) jumpBottom();
}

function setLogFilter(f, btn) {
    logFilter = f;
    document.querySelectorAll('.pill-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    renderLogs(cacheLogs);
}

function toggleAutoScroll() {
    autoScroll = !autoScroll;
    const btn = document.getElementById('btn-autoscroll');
    if (autoScroll) { btn.classList.add('active'); jumpBottom(); }
    else btn.classList.remove('active');
}

function handleScroll() {
    const s = document.getElementById('stream');
    const near = s.scrollHeight - s.scrollTop - s.clientHeight < 60;
    document.getElementById('jump').style.display = near ? 'none' : 'block';
}

function jumpBottom() {
    const s = document.getElementById('stream');
    s.scrollTop = s.scrollHeight;
    document.getElementById('jump').style.display = 'none';
}

function renderAccounts(accounts) {
    const container = document.getElementById('acc-list');
    document.getElementById('acc-count').innerText = `${accounts.length} Active`;

    const allPaused = accounts.length > 0 && accounts.every(a => a.is_paused || a.status === 'PAUSED');
    const gbtn = document.getElementById('btn-pause-all');
    if (gbtn) {
        if (allPaused) {
            gbtn.innerHTML = '<i class="fa-solid fa-play"></i> <span>Resume All</span>';
            gbtn.style.color = 'var(--c1)';
            gbtn.style.borderColor = 'rgba(0,255,200,0.4)';
        } else {
            gbtn.innerHTML = '<i class="fa-solid fa-pause"></i> <span>Pause All</span>';
            gbtn.style.color = '';
            gbtn.style.borderColor = '';
        }
    }

    if (accounts.length === 0) {
        container.innerHTML = `
            <div class="empty">
                <i class="fa-solid fa-ghost"></i>
                <p>Belum ada akun aktif. Klik "+ Add Account" untuk mulai farming!</p>
                <button class="btn btn-primary" onclick="openAddModal()"><i class="fa-solid fa-plus"></i> Add First Account</button>
            </div>
        `;
        return;
    }

    if (container.querySelector('.empty')) container.innerHTML = '';

    const uids = new Set(accounts.map(a => String(a.uid)));
    container.querySelectorAll('.acc').forEach(c => {
        if (!uids.has(c.dataset.uid)) c.remove();
    });

    accounts.forEach(acc => {
        const uid = String(acc.uid);
        const gained = acc.gained_exp || 0;
        const isPaused = Boolean(acc.is_paused || acc.status === 'PAUSED');
        const uptimeSec = Math.floor(acc.uptime_seconds || 0);
        const status = isPaused ? 'PAUSED' : (acc.status || 'ONLINE');
        const sclass = isPaused ? 'paused' : (status === 'IN_MATCH' ? 'in_match' : (status === 'SEARCHING' ? 'searching' : (status === 'ONLINE' ? 'online' : 'error')));
        const stext = isPaused ? 'Paused' : (status === 'IN_MATCH' ? `In Match (${acc.active_matches || 1})` : status);

        const lvl = Math.max(1, parseInt(acc.level) || 1);
        const nextLvl = Math.min(100, lvl + 1);
        const baseExp = EXP_TABLE[lvl] !== undefined ? EXP_TABLE[lvl] : 0;
        const targetExp = EXP_TABLE[nextLvl] !== undefined ? EXP_TABLE[nextLvl] : (baseExp + 50000);
        const needed = Math.max(1, targetExp - baseExp);
        const earned = Math.max(0, acc.current_exp - baseExp);
        const remain = Math.max(0, targetExp - acc.current_exp);
        const pct = lvl >= 100 ? 100 : Math.min(100, Math.max(0, (earned / needed) * 100));

        let card = document.getElementById('card-' + uid);
        if (!card) {
            card = document.createElement('div');
            card.id = 'card-' + uid;
            card.className = 'acc';
            card.dataset.uid = uid;
            container.appendChild(card);
        }

        card.dataset.nick = acc.nickname || '';
        card.dataset.status = sclass;
        card.dataset.paused = isPaused ? '1' : '0';

        const isBr = lvl < 3;
        const modeBadge = isBr
            ? `<span class="badge-mode br"><i class="fa-solid fa-crosshairs"></i> BR Lvl &lt; 3</span>`
            : `<span class="badge-mode lw"><i class="fa-solid fa-shield-halved"></i> Lone Wolf</span>`;

        card.innerHTML = `
            <div class="acc-top">
                <div class="acc-id">
                    <div class="acc-ava">
                        <i class="fa-solid fa-gamepad"></i>
                        <span class="lv">L${acc.level || 1}</span>
                    </div>
                    <div style="min-width:0; flex:1;">
                        <div class="acc-name">
                            ${esc(acc.nickname)}
                            <span class="badge-region">${esc(acc.region || 'BD')}</span>
                            ${modeBadge}
                        </div>
                        <div class="acc-sub">
                            <span class="acc-uid">UID: ${uid}</span>
                            <button class="copy-btn" onclick="copyUid('${uid}')" title="Copy UID"><i class="fa-regular fa-copy"></i></button>
                            <span class="uptime ${isPaused ? 'paused' : ''}" title="In-Game Playtime">
                                <i class="fa-solid fa-stopwatch"></i>
                                <span class="uptime-val" data-uid="${uid}" data-sec="${uptimeSec}" data-paused="${isPaused ? '1' : '0'}">${fmtDur(uptimeSec)}</span>
                            </span>
                        </div>
                    </div>
                </div>
                <div class="status ${sclass}">
                    <span class="pulse-dot"></span>
                    <span>${stext}</span>
                </div>
            </div>

            <div class="exp-grid">
                <div class="exp-cell">
                    <span class="lbl">Initial</span>
                    <span class="val">${(acc.initial_exp || 0).toLocaleString()}</span>
                </div>
                <div class="exp-cell">
                    <span class="lbl">Current</span>
                    <span class="val">${(acc.current_exp || 0).toLocaleString()}</span>
                </div>
                <div class="exp-cell">
                    <span class="lbl">Gain</span>
                    <span class="val gain">+${gained.toLocaleString()}</span>
                </div>
            </div>

            <div class="prog">
                <div class="prog-head">
                    <span class="prog-lv">
                        <i class="fa-solid fa-angles-up" style="color:var(--c1);"></i>
                        Level ${lvl} → <strong>L${nextLvl}</strong>
                    </span>
                    <span class="prog-need">
                        <i class="fa-solid fa-bolt"></i> ${remain.toLocaleString()} EXP
                    </span>
                </div>
                <div class="prog-track" title="${lvl}: ${earned.toLocaleString()} / ${needed.toLocaleString()} EXP">
                    <div class="prog-fill" style="width: ${pct.toFixed(1)}%"></div>
                </div>
                <div class="prog-foot">
                    <span>${earned.toLocaleString()} / ${needed.toLocaleString()}</span>
                    <span class="pct">${pct.toFixed(1)}%</span>
                </div>
            </div>

            <div class="acc-foot">
                <span class="last"><i class="fa-solid fa-clock" style="opacity:.6;"></i> ${esc(acc.last_match_time || 'Running...')}</span>
                <div class="acc-actions">
                    <button class="act ${isPaused ? 'resume' : 'pause'}" onclick="togglePause('${uid}')" title="${isPaused ? 'Resume' : 'Pause'}">
                        <i class="fa-solid ${isPaused ? 'fa-play' : 'fa-pause'}"></i>
                    </button>
                    <button class="act" onclick="restartAcc('${uid}')" title="Restart"><i class="fa-solid fa-arrow-rotate-right"></i></button>
                    <button class="act" onclick="refreshAcc('${uid}')" title="Refresh"><i class="fa-solid fa-arrows-rotate"></i></button>
                    <button class="act danger" onclick="delAccount('${uid}', '${esc(acc.auth_uid || '')}')" title="Delete"><i class="fa-solid fa-trash"></i></button>
                </div>
            </div>
        `;
    });

    filterAccounts();
}

function renderLogs(logs) {
    const stream = document.getElementById('stream');
    let filtered = logs;
    if (logFilter === 'match') filtered = logs.filter(l => l.message.includes('Match') || l.message.includes('⚔'));
    else if (logFilter === 'success') filtered = logs.filter(l => l.level === 'success' || l.message.includes('EXP'));
    else if (logFilter === 'error') filtered = logs.filter(l => l.level === 'error' || l.level === 'warning');

    stream.innerHTML = filtered.map(log => {
        const lvl = log.level || 'info';
        return `<div class="log-line"><span class="ts">[${esc(log.time || '00:00:00')}]</span><span class="msg ${lvl}">${esc(log.message)}</span></div>`;
    }).join('');

    if (autoScroll) jumpBottom();
}

function setTxt(id, v) {
    const el = document.getElementById(id);
    if (el) el.innerText = (v !== undefined && v !== null) ? v : '';
}

function setHtml(id, v) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = (v !== undefined && v !== null) ? v : '';
}

async function fetchStats() {
    try {
        const res = await fetch('/api/stats');
        const data = await res.json();

        setTxt('s-accounts', data.total_accounts);
        setTxt('s-exp', '+' + (data.total_gained_exp || 0).toLocaleString());
        setTxt('s-matches', data.total_matches);

        const online = data.accounts.filter(a => a.status === 'ONLINE' || a.status === 'IN_MATCH').length;
        setHtml('s-online', `<i class="fa-solid fa-circle-check"></i> ${online} Online`);
        setHtml('s-rate', `<i class="fa-solid fa-gauge-high"></i> ~${(data.exp_per_hour || 0).toLocaleString()} EXP/hr`);
        setHtml('s-active', `<i class="fa-solid fa-gamepad"></i> ${data.total_active_matches || 0} In Match`);

        setTxt('m-rate', `~${(data.exp_per_hour || 0).toLocaleString()} EXP/hr`);
        setTxt('m-matches', data.total_matches);

        cacheAcc = data.accounts;
        renderAccounts(data.accounts);

        cacheLogs = data.logs;
        renderLogs(data.logs);
    } catch (err) {
        console.warn("Stats poll error:", err);
    }
}

setInterval(() => {
    const sec = Math.floor((Date.now() - clientTime) / 1000);
    const h = String(Math.floor(sec / 3600)).padStart(2, '0');
    const m = String(Math.floor((sec % 3600) / 60)).padStart(2, '0');
    const s = String(sec % 60).padStart(2, '0');
    setTxt('s-uptime', `${h}:${m}:${s}`);

    document.querySelectorAll('.uptime-val').forEach(el => {
        if (el.dataset.paused !== '1') {
            let cur = parseInt(el.dataset.sec || '0', 10) + 1;
            el.dataset.sec = cur;
            el.innerText = fmtDur(cur);
        }
    });
}, 1000);

document.getElementById('add-modal').addEventListener('click', function(e) {
    if (e.target === this) closeAddModal();
});
document.getElementById('dev-modal').addEventListener('click', function(e) {
    if (e.target === this) closeDevModal();
});

fetchStats();
setInterval(fetchStats, 2000);
</script>
</body>
</html>
"""


# ============================================================
#  HTTP HANDLERS
# ============================================================

async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html", charset="utf-8")


async def handle_get_stats(request: web.Request) -> web.Response:
    accounts_data = list(bot_state.accounts.values())
    accounts_data.sort(key=lambda x: x.get("gained_exp", 0), reverse=True)
    uptime_sec = max(1, int(time.time() - bot_state.start_time))
    total_gained = bot_state.total_gained_exp
    exp_per_hour = int((total_gained / uptime_sec) * 3600)
    total_active_matches = sum(acc.get("active_matches", 0) for acc in accounts_data)

    for acc in accounts_data:
        uid_k = str(acc.get("uid", ""))
        acc["uptime_seconds"] = bot_state.get_account_uptime(uid_k)
        acc["is_paused"] = bot_state.is_paused(uid_k)

    return web.json_response({
        "total_accounts": len(bot_state.accounts),
        "total_matches": bot_state.total_matches,
        "total_active_matches": total_active_matches,
        "total_gained_exp": total_gained,
        "exp_per_hour": exp_per_hour,
        "accounts": accounts_data,
        "logs": bot_state.logs[-80:],
        "uptime": uptime_sec
    })


async def handle_add_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        accounts_file = "accounts.json"
        existing = []
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        if "uid" in data and "password" in data:
            uid = str(data["uid"]).strip()
            pwd = str(data["password"]).strip()
            if not uid or not pwd:
                return web.json_response({"status": "error", "error": "UID and Password required"})

            if uid in bot_state.account_workers:
                try:
                    bot_state.account_workers[uid].cancel()
                except Exception:
                    pass
                bot_state.account_workers.pop(uid, None)

            existing = [acc for acc in existing if str(acc.get("uid", "")) != uid]
            existing.append({"uid": uid, "password": pwd})
            identifier = uid
        elif "token" in data:
            token = str(data["token"]).strip()
            if not token:
                return web.json_response({"status": "error", "error": "Token required"})

            tok_key = token[:16]
            for k in list(bot_state.account_workers.keys()):
                if k == tok_key or k.startswith(tok_key[:10]) or tok_key.startswith(k[:10]):
                    try:
                        bot_state.account_workers[k].cancel()
                    except Exception:
                        pass
                    bot_state.account_workers.pop(k, None)

            existing = [acc for acc in existing if acc.get("token", "") != token]
            existing.append({"token": token})
            identifier = f"Token_{token[:8]}..."
        else:
            return web.json_response({"status": "error", "error": "Invalid payload"})

        with open(accounts_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        bot_state.log(f"New account added: {identifier}", "success")
        if "on_account_added" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_account_added"](data))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_delete_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        req_uid = str(data.get("uid", "")).strip()
        req_auth_uid = str(data.get("auth_uid", "")).strip()
        if not req_uid and not req_auth_uid:
            return web.json_response({"status": "error", "error": "UID required"})

        candidate_ids = set()
        if req_uid: candidate_ids.add(req_uid)
        if req_auth_uid: candidate_ids.add(req_auth_uid)

        for cid in list(candidate_ids):
            if cid in bot_state.game_to_auth_id:
                candidate_ids.add(str(bot_state.game_to_auth_id[cid]))
            if cid in bot_state.auth_to_game_id:
                candidate_ids.add(str(bot_state.auth_to_game_id[cid]))

        target_tokens = set()
        for cid in list(candidate_ids):
            acc_info = bot_state.accounts.get(cid, {})
            if acc_info:
                if acc_info.get("auth_uid"): candidate_ids.add(str(acc_info["auth_uid"]))
                if acc_info.get("uid"): candidate_ids.add(str(acc_info["uid"]))
                t = acc_info.get("token") or acc_info.get("access_token")
                if t: target_tokens.add(str(t))

        for cid in list(candidate_ids):
            creds = bot_state.account_credentials.get(cid, {})
            if creds:
                if creds.get("auth_uid"): candidate_ids.add(str(creds["auth_uid"]))
                if creds.get("account_id"): candidate_ids.add(str(creds["account_id"]))
                t = creds.get("token") or creds.get("access_token") or creds.get("auth_token")
                if t: target_tokens.add(str(t))

        token_cache_file = "token_cache.json"
        if os.path.exists(token_cache_file):
            try:
                with open(token_cache_file, "r", encoding="utf-8") as f:
                    tcache = json.load(f)
                dirty = False
                for k, v in list(tcache.items()):
                    k_str = str(k)
                    v_acc_id = str(v.get("account_id", ""))
                    v_auth_uid = str(v.get("auth_uid", ""))
                    if k_str in candidate_ids or v_acc_id in candidate_ids or v_auth_uid in candidate_ids:
                        candidate_ids.add(k_str)
                        if v_acc_id: candidate_ids.add(v_acc_id)
                        if v_auth_uid: candidate_ids.add(v_auth_uid)
                        del tcache[k]
                        dirty = True
                if dirty:
                    with open(token_cache_file, "w", encoding="utf-8") as f:
                        json.dump(tcache, f, indent=2)
            except Exception:
                pass

        accounts_file = "accounts.json"
        if os.path.exists(accounts_file):
            try:
                with open(accounts_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                new_existing = []
                for acc in existing:
                    acc_uid = str(acc.get("uid", "")).strip()
                    acc_tok = str(acc.get("token", "")).strip()
                    is_match = False
                    if acc_uid and acc_uid in candidate_ids: is_match = True
                    if acc_tok and (acc_tok in candidate_ids or acc_tok in target_tokens): is_match = True
                    for tok in target_tokens:
                        if acc_tok and (acc_tok.startswith(tok[:16]) or tok.startswith(acc_tok[:16])):
                            is_match = True
                    if not is_match:
                        new_existing.append(acc)
                with open(accounts_file, "w", encoding="utf-8") as f:
                    json.dump(new_existing, f, indent=2)
            except Exception:
                pass

        devices_file = "devices.json"
        if os.path.exists(devices_file):
            try:
                with open(devices_file, "r", encoding="utf-8") as f:
                    devices_data = json.load(f)
                dirty = False
                for dev_k in list(devices_data.keys()):
                    dev_k_str = str(dev_k)
                    if dev_k_str in candidate_ids:
                        del devices_data[dev_k]
                        dirty = True
                    else:
                        for tok in target_tokens:
                            if dev_k_str == tok[:16] or tok.startswith(dev_k_str):
                                del devices_data[dev_k]
                                dirty = True
                                break
                if dirty:
                    with open(devices_file, "w", encoding="utf-8") as f:
                        json.dump(devices_data, f, indent=4)
            except Exception:
                pass

        for cid in candidate_ids:
            bot_state.accounts.pop(cid, None)
            bot_state.account_credentials.pop(cid, None)
            bot_state.auth_to_game_id.pop(cid, None)
            bot_state.game_to_auth_id.pop(cid, None)
            bot_state.account_token_map.pop(cid, None)

        cancelled_keys = []
        for k, worker in list(bot_state.account_workers.items()):
            k_str = str(k)
            should_cancel = False
            if k_str in candidate_ids: should_cancel = True
            for tok in target_tokens:
                if k_str == tok[:16] or tok.startswith(k_str[:10]): should_cancel = True
            if should_cancel:
                try: worker.cancel()
                except Exception: pass
                cancelled_keys.append(k)

        for k in cancelled_keys:
            bot_state.account_workers.pop(k, None)
        for cid in candidate_ids:
            bot_state.close_writers_for_account(cid)

        if "on_account_deleted" in bot_state.refresh_callbacks:
            try:
                asyncio.create_task(bot_state.refresh_callbacks["on_account_deleted"](list(candidate_ids)))
            except Exception:
                pass

        target_repr = req_uid or req_auth_uid
        bot_state.log(f"Account {target_repr} deleted.", "warning", target_repr)
        bot_state.recalc_totals()
        return web.json_response({"status": "ok", "deleted": list(candidate_ids)})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_refresh_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_restart_account(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if "on_restart_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_restart_account"](uid))
        elif "on_refresh_account" in bot_state.refresh_callbacks:
            asyncio.create_task(bot_state.refresh_callbacks["on_refresh_account"](uid))
        return web.json_response({"status": "ok"})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_clear_logs(request: web.Request) -> web.Response:
    bot_state.logs.clear()
    return web.json_response({"status": "ok"})


async def handle_toggle_pause(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        uid = str(data.get("uid", "")).strip()
        if not uid:
            return web.json_response({"status": "error", "error": "UID required"})
        is_paused = bot_state.toggle_pause(uid)
        return web.json_response({"status": "ok", "is_paused": is_paused})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


async def handle_toggle_pause_all(request: web.Request) -> web.Response:
    try:
        paused_state = bot_state.toggle_pause_all()
        return web.json_response({"status": "ok", "all_paused": paused_state})
    except Exception as e:
        return web.json_response({"status": "error", "error": str(e)})


# ============================================================
#  START WEB DASHBOARD
# ============================================================

async def start_web_dashboard(host: str = "2001:41d0:306:277a::2417", port: int = 5000):
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_post("/api/account/add", handle_add_account)
    app.router.add_post("/api/account/delete", handle_delete_account)
    app.router.add_post("/api/account/refresh", handle_refresh_account)
    app.router.add_post("/api/account/restart", handle_restart_account)
    app.router.add_post("/api/account/pause", handle_toggle_pause)
    app.router.add_post("/api/account/pause_all", handle_toggle_pause_all)
    app.router.add_post("/api/logs/clear", handle_clear_logs)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    return runner