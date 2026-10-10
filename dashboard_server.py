# -*- coding: utf-8 -*-
"""
FreeFire Level Up Bot - Professional Web Dashboard & Real-Time EXP Tracker
Embedded Async Web Server (aiohttp) - Single File Edition
Redesigned by malz codex
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
#  EMBEDDED HTML DASHBOARD (single-file, premium rebuild)
# ============================================================

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<meta name="theme-color" content="#05030d">
<title>MALZ CODEX | Level Up Command Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
:root{
  --bg:#05030d;
  --bg-2:#0a0718;
  --panel:rgba(19,14,38,0.72);
  --panel-2:rgba(30,20,60,0.55);
  --panel-hover:rgba(38,26,72,0.85);
  --border:rgba(168,85,247,0.16);
  --border-2:rgba(168,85,247,0.32);
  --border-hot:rgba(0,255,213,0.55);
  --cyan:#00ffd5;
  --cyan-dim:#00d4b3;
  --violet:#a855f7;
  --violet-2:#c084fc;
  --blue:#3b82f6;
  --blue-2:#66d9ff;
  --green:#22c55e;
  --amber:#f59e0b;
  --amber-2:#ffb84d;
  --rose:#f43f5e;
  --rose-2:#ff5c8a;
  --txt:#f4f6ff;
  --txt-2:#a8b0d8;
  --txt-3:#6d76a0;
  --glow-cyan:0 0 24px rgba(0,255,213,0.35);
  --glow-violet:0 0 24px rgba(168,85,247,0.42);
  --shadow:0 18px 44px -10px rgba(0,0,0,0.85);
  --r-lg:22px;
  --r-md:16px;
  --r-sm:10px;
}
*{box-sizing:border-box;margin:0;padding:0;font-family:'Plus Jakarta Sans',sans-serif;-webkit-tap-highlight-color:transparent}
html,body{height:100%}
body{
  background:var(--bg);
  color:var(--txt);
  min-height:100vh;
  overflow-x:hidden;
  background-attachment:fixed;
  background-image:
    radial-gradient(ellipse 900px 600px at 8% -5%, rgba(168,85,247,0.20), transparent 55%),
    radial-gradient(ellipse 800px 700px at 96% 105%, rgba(0,255,213,0.14), transparent 58%),
    radial-gradient(ellipse 700px 500px at 50% 50%, rgba(59,130,246,0.09), transparent 62%),
    linear-gradient(180deg,#05030d 0%,#0d0820 55%,#080517 100%);
}
body::before{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background-size:44px 44px;
  background-image:
    linear-gradient(to right,rgba(168,85,247,0.035) 1px,transparent 1px),
    linear-gradient(to bottom,rgba(0,255,213,0.028) 1px,transparent 1px);
  mask-image:radial-gradient(ellipse at 50% 30%,#000 30%,transparent 78%);
  -webkit-mask-image:radial-gradient(ellipse at 50% 30%,#000 30%,transparent 78%);
}
.app{position:relative;z-index:1;max-width:1560px;margin:0 auto;padding:24px}

/* ============ press feedback for all interactive ============ */
.btn,.icon-btn,.btn-copy,.filter-btn,.cpill,.toggle-btn,.btn-pause-all,.mnav-item,.avatar-ring,.stat-card,.acc-card,.form-control{
  transition:transform .18s cubic-bezier(.34,1.56,.64,1),box-shadow .25s ease,background .25s ease,border-color .25s ease,color .2s ease,opacity .2s ease;
  will-change:transform;
}
.btn:active,.icon-btn:active,.btn-copy:active,.filter-btn:active,.cpill:active,.toggle-btn:active,.btn-pause-all:active,.mnav-item:active{transform:scale(.9);transition:transform .08s ease}
.btn-primary:active{transform:scale(.94) translateY(1px)}
.avatar-ring:active{transform:scale(.9) rotate(-6deg);transition:transform .12s ease}
.acc-card:active{transform:scale(.985)}
.stat-card:active{transform:scale(.975)}
.form-control:focus{transform:scale(1.012)}
.mnav-item:active i{transform:scale(1.25) translateY(-2px);transition:transform .15s cubic-bezier(.34,1.56,.64,1)}
.mnav-item i{transition:transform .2s cubic-bezier(.34,1.56,.64,1)}
.icon-btn i{transition:transform .2s cubic-bezier(.34,1.56,.64,1)}
.icon-btn:active i{transform:scale(1.15);transition:transform .15s ease}
.btn-copy:active{transform:scale(.75);color:var(--cyan)}

/* ============ topbar ============ */
.topbar{
  display:flex;align-items:center;justify-content:space-between;gap:18px;
  padding:18px 26px;
  background:var(--panel);
  border:1px solid var(--border);
  border-radius:var(--r-lg);
  backdrop-filter:blur(22px) saturate(1.2);
  -webkit-backdrop-filter:blur(22px) saturate(1.2);
  box-shadow:var(--shadow);
  margin-bottom:22px;
  position:relative;
  overflow:hidden;
}
.topbar::after{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(0,255,213,0.5) 30%,rgba(168,85,247,0.5) 70%,transparent);
  opacity:.6;
}
.brand{display:flex;align-items:center;gap:16px;min-width:0}
.avatar-ring{
  width:56px;height:56px;border-radius:50%;padding:3px;flex-shrink:0;
  background:conic-gradient(from 0deg,#a855f7,#00ffd5,#3b82f6,#a855f7);
  animation:avatarPulse 3.4s ease-in-out infinite alternate;
  cursor:pointer;
}
.avatar-ring img{width:100%;height:100%;border-radius:50%;object-fit:cover;border:2px solid #05030d;display:block;background:#1a1030}
@keyframes avatarPulse{
  from{box-shadow:0 0 16px rgba(168,85,247,0.55),0 0 28px rgba(168,85,247,0.20)}
  to{box-shadow:0 0 22px rgba(0,255,213,0.55),0 0 36px rgba(0,255,213,0.28)}
}
.brand-text{min-width:0;overflow:hidden}
.brand-text h1{
  font-size:23px;font-weight:900;letter-spacing:-.6px;line-height:1.1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  background:linear-gradient(90deg,#ffffff 10%,#c084fc 55%,#00ffd5 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
.brand-text h1 span{font-weight:500;font-size:14px;color:var(--txt-3);-webkit-text-fill-color:var(--txt-3)}
.brand-sub{display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--txt-2);margin-top:4px;flex-wrap:wrap}
.badge-live{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(0,255,213,0.10);border:1px solid rgba(0,255,213,0.32);
  color:var(--cyan);padding:3px 10px;border-radius:20px;
  font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.6px;
}
.r-dot{position:relative;width:7px;height:7px;background:var(--cyan);border-radius:50%}
.r-dot::after{content:'';position:absolute;inset:-4px;border:2px solid var(--cyan);border-radius:50%;animation:radar 1.7s ease-out infinite}
@keyframes radar{0%{transform:scale(.55);opacity:1}100%{transform:scale(2.2);opacity:0}}
.tagline-chip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;color:var(--txt-3);padding:3px 10px;background:rgba(168,85,247,0.06);border:1px solid rgba(168,85,247,0.14);border-radius:20px;font-weight:600}
.topbar-right{display:flex;align-items:center;gap:10px;flex-shrink:0}

/* ============ buttons ============ */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 18px;border-radius:var(--r-md);font-size:13.5px;font-weight:700;cursor:pointer;border:1px solid transparent;outline:none;user-select:none;white-space:nowrap;position:relative;overflow:hidden}
.btn-primary{background:linear-gradient(135deg,#a855f7 0%,#3b82f6 50%,#00ffd5 100%);color:#05030d;font-weight:800;box-shadow:0 6px 22px rgba(168,85,247,0.4),0 4px 16px rgba(0,255,213,0.28)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(168,85,247,0.55),0 6px 22px rgba(0,255,213,0.36)}
.btn-secondary{background:rgba(255,255,255,0.045);border-color:rgba(168,85,247,0.28);color:var(--txt)}
.btn-secondary:hover{background:rgba(168,85,247,0.14);border-color:var(--border-hot)}
.btn-primary::after,.btn-secondary::after,.btn-pause-all::after{content:'';position:absolute;inset:0;border-radius:inherit;background:radial-gradient(circle,rgba(255,255,255,0.42) 0%,transparent 62%);opacity:0;transform:scale(.4);transition:transform .4s ease,opacity .4s ease;pointer-events:none}
.btn-primary:active::after,.btn-secondary:active::after,.btn-pause-all:active::after{opacity:1;transform:scale(1.4);transition:transform 0s,opacity .35s ease-out}

/* ============ stats hero ============ */
.hero{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:22px}
.stat-card{
  background:var(--panel);border:1px solid var(--border);border-radius:var(--r-lg);
  padding:20px 22px;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  box-shadow:var(--shadow);display:flex;align-items:center;justify-content:space-between;
  position:relative;overflow:hidden;cursor:pointer;
}
.stat-card::before{content:'';position:absolute;left:0;top:0;bottom:0;width:4px;background:transparent;transition:background .3s}
.stat-card:hover{transform:translateY(-3px);border-color:var(--border-hot);box-shadow:var(--glow-cyan)}
.stat-card.c-cyan::before{background:var(--cyan)}
.stat-card.c-green::before{background:var(--green)}
.stat-card.c-violet::before{background:var(--violet)}
.stat-card.c-amber::before{background:var(--amber)}
.stat-data p{font-size:11.5px;color:var(--txt-2);font-weight:700;margin-bottom:8px;text-transform:uppercase;letter-spacing:.8px}
.stat-data h2{font-size:27px;font-weight:800;letter-spacing:-.5px;color:#fff;font-family:'JetBrains Mono',monospace;line-height:1}
.stat-badge{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:700;padding:3px 9px;border-radius:7px;margin-top:8px;border:1px solid transparent}
.stat-badge.b-cyan{background:rgba(0,255,213,0.10);color:var(--cyan);border-color:rgba(0,255,213,0.22)}
.stat-badge.b-green{background:rgba(34,197,94,0.12);color:#4ade80;border-color:rgba(34,197,94,0.28)}
.stat-badge.b-violet{background:rgba(168,85,247,0.14);color:var(--violet-2);border-color:rgba(168,85,247,0.30)}
.stat-badge.b-amber{background:rgba(245,158,11,0.13);color:var(--amber-2);border-color:rgba(245,158,11,0.30)}
.s-icon{width:54px;height:54px;border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
.s-icon.i-cyan{background:rgba(0,255,213,0.10);color:var(--cyan);border:1px solid rgba(0,255,213,0.20)}
.s-icon.i-green{background:rgba(34,197,94,0.12);color:#4ade80;border:1px solid rgba(34,197,94,0.24)}
.s-icon.i-violet{background:rgba(168,85,247,0.14);color:var(--violet-2);border:1px solid rgba(168,85,247,0.28)}
.s-icon.i-amber{background:rgba(245,158,11,0.13);color:var(--amber-2);border:1px solid rgba(245,158,11,0.28)}

/* ============ workspace ============ */
.workspace{display:grid;grid-template-columns:1fr 500px;gap:22px}
.panel{
  background:var(--panel);border:1px solid var(--border);border-radius:var(--r-lg);
  padding:22px;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  box-shadow:var(--shadow);display:flex;flex-direction:column;position:relative;overflow:hidden;
}
.panel::after{content:'';position:absolute;top:0;left:20%;right:20%;height:1px;background:linear-gradient(90deg,transparent,rgba(0,255,213,0.28),transparent);opacity:.7}
.p-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid rgba(168,85,247,0.10);flex-wrap:wrap;gap:12px}
.p-title{display:flex;align-items:center;gap:12px}
.p-title h3{font-size:17px;font-weight:800;color:#fff;letter-spacing:-.2px}
.counter-pill{background:rgba(0,255,213,0.10);color:var(--cyan);border:1px solid rgba(0,255,213,0.24);padding:3px 11px;border-radius:20px;font-size:11.5px;font-weight:800;font-family:'JetBrains Mono',monospace}
.p-actions{display:flex;align-items:center;gap:10px}

/* filter row */
.filter-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.search{flex:1;min-width:220px;position:relative}
.search i{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:var(--txt-3);font-size:13px;transition:color .2s,transform .2s}
.search:focus-within i{color:var(--cyan);transform:translateY(-50%) scale(1.15)}
.search input{width:100%;background:rgba(255,255,255,0.035);border:1px solid rgba(168,85,247,0.20);border-radius:var(--r-md);padding:10px 14px 10px 40px;color:#fff;font-size:13px;outline:none;transition:all .2s;font-weight:500}
.search input::placeholder{color:var(--txt-3)}
.search input:focus{border-color:var(--border-hot);background:rgba(0,255,213,0.06);box-shadow:0 0 14px rgba(0,255,213,0.22)}
.ftabs{display:flex;gap:5px;background:rgba(0,0,0,0.32);padding:4px;border-radius:var(--r-md);border:1px solid rgba(168,85,247,0.14)}
.filter-btn{background:transparent;border:none;color:var(--txt-3);padding:7px 13px;border-radius:9px;font-size:12px;font-weight:700;cursor:pointer;transition:all .2s}
.filter-btn.active{background:rgba(0,255,213,0.14);color:var(--cyan);box-shadow:inset 0 0 0 1px rgba(0,255,213,0.28)}

/* accounts grid */
.accounts{display:flex;flex-direction:column;gap:14px;max-height:720px;overflow-y:auto;padding-right:6px}
.accounts::-webkit-scrollbar{width:6px}
.accounts::-webkit-scrollbar-track{background:transparent}
.accounts::-webkit-scrollbar-thumb{background:rgba(168,85,247,0.30);border-radius:6px}
.accounts::-webkit-scrollbar-thumb:hover{background:rgba(0,255,213,0.42)}

/* account card */
.acc-card{
  background:linear-gradient(155deg,rgba(14,10,32,0.72) 0%,rgba(22,14,46,0.62) 100%);
  border:1px solid rgba(168,85,247,0.16);border-radius:18px;padding:18px 20px;position:relative;
  overflow:hidden;
}
.acc-card::before{content:'';position:absolute;inset:0;border-radius:inherit;padding:1px;background:linear-gradient(135deg,rgba(168,85,247,0.30),transparent 40%,transparent 60%,rgba(0,255,213,0.22));-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none;opacity:0;transition:opacity .3s}
.acc-card:hover::before{opacity:1}
.acc-card:hover{background:linear-gradient(155deg,rgba(22,16,48,0.92) 0%,rgba(32,22,68,0.85) 100%);transform:translateY(-2px);box-shadow:0 12px 32px -8px rgba(0,0,0,0.7),0 0 0 1px rgba(0,255,213,0.28)}

.acc-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}
.acc-id{display:flex;align-items:center;gap:12px;min-width:0;flex:1}
.acc-avatar{width:46px;height:46px;border-radius:13px;background:linear-gradient(135deg,#1a1440,#2e1f68);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:800;color:var(--cyan);border:1px solid rgba(0,255,213,0.32);position:relative;flex-shrink:0;font-family:'JetBrains Mono',monospace;letter-spacing:-1px;text-shadow:0 0 10px rgba(0,255,213,0.5)}
.acc-card:hover .acc-avatar{box-shadow:0 0 16px rgba(0,255,213,0.42);transform:scale(1.04)}
.level-badge{position:absolute;bottom:-6px;right:-6px;background:#0a0618;border:1.5px solid var(--cyan);color:#fff;font-size:9px;font-weight:800;padding:1px 5px;border-radius:7px;font-family:'JetBrains Mono',monospace;line-height:1.3;box-shadow:0 0 10px rgba(0,255,213,0.35)}
.acc-meta{min-width:0;flex:1}
.acc-name{font-size:15.5px;font-weight:800;color:#fff;display:flex;align-items:center;gap:7px;flex-wrap:wrap;line-height:1.2}
.region-tag{background:rgba(59,130,246,0.16);color:var(--blue-2);border:1px solid rgba(59,130,246,0.35);padding:1px 7px;border-radius:6px;font-size:10px;font-weight:800;letter-spacing:.4px;font-family:'JetBrains Mono',monospace}
.mode-badge{padding:1px 7px;border-radius:6px;font-size:10px;font-weight:800;font-family:'JetBrains Mono',monospace;letter-spacing:.3px;display:inline-flex;align-items:center;gap:4px}
.mode-badge.br{background:rgba(245,158,11,0.14);color:var(--amber-2);border:1px solid rgba(245,158,11,0.36)}
.mode-badge.lw{background:rgba(168,85,247,0.16);color:var(--violet-2);border:1px solid rgba(168,85,247,0.38)}
.acc-uid-line{display:flex;align-items:center;gap:6px;margin-top:5px;flex-wrap:wrap}
.acc-uid{font-size:11.5px;color:var(--txt-3);font-family:'JetBrains Mono',monospace;font-weight:500}
.btn-copy{background:transparent;border:none;color:var(--txt-3);cursor:pointer;font-size:11px;padding:2px 5px;border-radius:5px;transition:all .2s}
.btn-copy:hover{color:var(--cyan);background:rgba(0,255,213,0.10)}
.uptime-pill{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--cyan);background:rgba(0,255,213,0.08);border:1px solid rgba(0,255,213,0.24);padding:2px 8px;border-radius:7px;letter-spacing:.2px}
.uptime-pill.paused{color:var(--amber-2);background:rgba(245,158,11,0.08);border-color:rgba(245,158,11,0.26)}

/* status pill */
.status-pill{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:800;padding:5px 12px;border-radius:20px;letter-spacing:.4px;flex-shrink:0;font-family:'JetBrains Mono',monospace}
.status-pill .r-dot{width:7px;height:7px}
.status-pill.online{background:rgba(0,255,213,0.11);color:var(--cyan);border:1px solid rgba(0,255,213,0.30)}
.status-pill.in_match{background:rgba(168,85,247,0.14);color:var(--violet-2);border:1px solid rgba(168,85,247,0.45);animation:pulse-border 1.6s infinite alternate}
.status-pill.searching{background:rgba(59,130,246,0.13);color:var(--blue-2);border:1px solid rgba(59,130,246,0.36)}
.status-pill.paused{background:rgba(245,158,11,0.11);color:var(--amber-2);border:1px solid rgba(245,158,11,0.40)}
.status-pill.paused .r-dot{background:var(--amber-2)}
.status-pill.paused .r-dot::after{border-color:var(--amber-2);animation:none;opacity:.3}
.status-pill.in_match .r-dot{background:var(--violet-2)}
.status-pill.in_match .r-dot::after{border-color:var(--violet-2)}
.status-pill.error{background:rgba(244,63,94,0.11);color:var(--rose-2);border:1px solid rgba(244,63,94,0.32)}
@keyframes pulse-border{0%{box-shadow:0 0 6px rgba(168,85,247,0.20)}100%{box-shadow:0 0 16px rgba(168,85,247,0.55)}}

/* exp strip */
.exp-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;background:rgba(0,0,0,0.28);border:1px solid rgba(168,85,247,0.10);border-radius:13px;padding:12px 14px;margin-bottom:12px}
.exp-col{display:flex;flex-direction:column;gap:4px;min-width:0}
.exp-col span{font-size:10px;color:var(--txt-3);text-transform:uppercase;font-weight:700;letter-spacing:.6px}
.exp-col strong{font-size:13.5px;font-weight:800;color:#fff;font-family:'JetBrains Mono',monospace;letter-spacing:-.2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.exp-col strong.gain{color:var(--cyan);text-shadow:0 0 10px rgba(0,255,213,0.4)}

/* progress bar */
.progress-box{margin-bottom:12px;background:rgba(255,255,255,0.02);padding:11px 13px;border-radius:13px;border:1px solid rgba(168,85,247,0.10);transition:all .3s}
.progress-box:hover{border-color:rgba(0,255,213,0.26);background:rgba(0,255,213,0.035)}
.prog-top{display:flex;justify-content:space-between;align-items:center;gap:8px;font-size:11px;margin-bottom:9px;font-weight:700}
.prog-tag{color:var(--txt);display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:700}
.prog-tag strong{color:var(--cyan);font-weight:800;font-family:'JetBrains Mono',monospace}
.prog-need{background:rgba(168,85,247,0.16);color:var(--violet-2);border:1px solid rgba(168,85,247,0.35);padding:3px 9px;border-radius:20px;font-size:10.5px;font-weight:800;display:inline-flex;align-items:center;gap:4px;font-family:'JetBrains Mono',monospace;animation:badgePulse 2.6s infinite ease-in-out}
@keyframes badgePulse{0%,100%{transform:scale(1);opacity:.96}50%{transform:scale(1.02);opacity:1;box-shadow:0 0 14px rgba(168,85,247,0.45)}}
.prog-track{height:10px;background:rgba(0,0,0,0.55);border-radius:12px;overflow:hidden;position:relative;border:1px solid rgba(168,85,247,0.14);box-shadow:inset 0 2px 5px rgba(0,0,0,0.7)}
.prog-fill{height:100%;background:linear-gradient(90deg,#3b82f6 0%,#00ffd5 25%,#a855f7 50%,#00ffd5 75%,#3b82f6 100%);background-size:200% 100%;border-radius:12px;transition:width .8s cubic-bezier(.34,1.56,.64,1);animation:progShift 3s infinite linear;position:relative;box-shadow:0 0 14px rgba(0,255,213,0.55),0 0 22px rgba(168,85,247,0.30)}
.prog-fill::before{content:'';position:absolute;inset:0;background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,0.72) 50%,transparent 100%);background-size:200% 100%;animation:shimmer 2.2s infinite linear;border-radius:12px;pointer-events:none}
.prog-fill::after{content:'';position:absolute;top:0;right:0;bottom:0;width:6px;background:#fff;border-radius:50%;box-shadow:0 0 8px #fff,0 0 14px var(--cyan)}
@keyframes progShift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
@keyframes shimmer{0%{transform:translateX(-150%)}100%{transform:translateX(150%)}}
.prog-bot{display:flex;justify-content:space-between;align-items:center;font-size:10.5px;color:var(--txt-3);margin-top:7px;font-weight:600}
.pct-pill{color:var(--cyan);font-weight:800;font-size:10.5px;background:rgba(0,255,213,0.08);padding:2px 8px;border-radius:9px;border:1px solid rgba(0,255,213,0.26);font-family:'JetBrains Mono',monospace}

/* mini stats grid (extra detail) */
.mini-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.mini-cell{background:rgba(0,0,0,0.22);border:1px solid rgba(168,85,247,0.08);border-radius:10px;padding:8px 10px;display:flex;flex-direction:column;gap:2px;min-width:0}
.mini-cell .k{font-size:9.5px;color:var(--txt-3);font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.mini-cell .v{font-size:12px;color:#fff;font-weight:700;font-family:'JetBrains Mono',monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mini-cell .v.likes{color:#ff6b9d}
.mini-cell .v.matches{color:var(--blue-2)}
.mini-cell .v.last{color:var(--amber-2)}

/* footer */
.acc-foot{display:flex;align-items:center;justify-content:space-between;padding-top:12px;border-top:1px solid rgba(168,85,247,0.10);gap:10px;flex-wrap:wrap}
.acc-foot-label{font-size:11px;color:var(--txt-3);font-weight:600;display:flex;align-items:center;gap:6px}
.acc-btns{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.icon-btn{width:34px;height:34px;border-radius:10px;background:rgba(168,85,247,0.08);border:1px solid rgba(168,85,247,0.20);color:var(--txt-2);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:13px}
.icon-btn:hover{background:rgba(0,255,213,0.14);color:var(--cyan);border-color:var(--cyan);transform:translateY(-1px)}
.icon-btn.danger:hover{background:rgba(244,63,94,0.14);color:var(--rose-2);border-color:var(--rose-2)}
.icon-btn.btn-pause{color:var(--amber-2)}
.icon-btn.btn-pause:hover{background:rgba(245,158,11,0.16);color:var(--amber-2);border-color:var(--amber-2)}
.icon-btn.btn-resume{background:rgba(0,255,213,0.12);color:var(--cyan);border-color:rgba(0,255,213,0.4)}
.icon-btn.btn-resume:hover{background:rgba(0,255,213,0.24);color:#fff;border-color:var(--cyan);box-shadow:0 0 12px rgba(0,255,213,0.4)}

.btn-pause-all{display:inline-flex;align-items:center;gap:6px;padding:7px 13px;font-size:12px;font-weight:700;border-radius:10px;background:rgba(245,158,11,0.11);border:1px solid rgba(245,158,11,0.34);color:var(--amber-2);cursor:pointer;position:relative;overflow:hidden}
.btn-pause-all:hover{background:rgba(245,158,11,0.20);border-color:var(--amber-2);box-shadow:0 0 12px rgba(245,158,11,0.30)}
.btn-pause-all.all-paused{background:rgba(0,255,213,0.11);border-color:rgba(0,255,213,0.40);color:var(--cyan)}
.btn-pause-all.all-paused:hover{background:rgba(0,255,213,0.20);border-color:var(--cyan);box-shadow:0 0 12px rgba(0,255,213,0.35)}

/* ============ console ============ */
.console-panel{height:820px}
.console-tools{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.cfilter{display:flex;gap:5px;flex-wrap:wrap}
.cpill{background:rgba(168,85,247,0.06);border:1px solid rgba(168,85,247,0.18);color:var(--txt-3);padding:5px 11px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;transition:all .2s}
.cpill.active{background:rgba(0,255,213,0.14);color:var(--cyan);border-color:rgba(0,255,213,0.34)}
.c-right{display:flex;align-items:center;gap:8px}
.toggle-btn{background:rgba(168,85,247,0.06);border:1px solid rgba(168,85,247,0.18);color:var(--txt-2);padding:5px 11px;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;display:inline-flex;align-items:center;gap:6px;transition:all .2s}
.toggle-btn.active{color:var(--cyan);border-color:rgba(0,255,213,0.38);background:rgba(0,255,213,0.10)}
.stream{flex:1;background:#04020c;border:1px solid rgba(168,85,247,0.12);border-radius:14px;padding:14px;font-family:'JetBrains Mono',monospace;font-size:12px;overflow-y:auto;display:flex;flex-direction:column;gap:5px;position:relative;box-shadow:inset 0 0 40px rgba(168,85,247,0.06)}
.stream::-webkit-scrollbar{width:6px}
.stream::-webkit-scrollbar-thumb{background:rgba(168,85,247,0.32);border-radius:3px}
.log-e{line-height:1.55;word-break:break-all;display:flex;align-items:flex-start;gap:8px;animation:logIn .25s ease-out;padding:2px 0}
@keyframes logIn{0%{opacity:0;transform:translateX(-8px)}100%{opacity:1;transform:translateX(0)}}
.log-ts{color:#4a4570;flex-shrink:0;font-size:11px;font-weight:500}
.log-icon{flex-shrink:0;font-size:11px;width:14px;text-align:center;padding-top:1px}
.log-txt{flex:1;font-weight:500}
.log-txt.info{color:#66d9ff}
.log-txt.success{color:var(--cyan)}
.log-txt.warning{color:var(--amber-2)}
.log-txt.error{color:var(--rose-2)}
.log-icon.info{color:#66d9ff}
.log-icon.success{color:var(--cyan)}
.log-icon.warning{color:var(--amber-2)}
.log-icon.error{color:var(--rose-2)}
.btn-jump{position:absolute;bottom:12px;right:14px;background:rgba(0,255,213,0.18);border:1px solid var(--cyan);color:#fff;padding:6px 13px;border-radius:20px;font-size:11px;font-weight:700;cursor:pointer;backdrop-filter:blur(8px);display:none;box-shadow:0 4px 14px rgba(0,0,0,0.55)}
.btn-jump:hover{background:var(--cyan);color:#05030d}

/* ============ empty ============ */
.empty{text-align:center;padding:64px 20px;color:var(--txt-3)}
.empty i{font-size:52px;margin-bottom:16px;color:rgba(168,85,247,0.16)}
.empty p{font-size:14px;color:var(--txt-2);margin-bottom:20px;font-weight:500}

/* ============ modal ============ */
.modal-bg{position:fixed;inset:0;background:rgba(4,2,14,0.88);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);display:none;align-items:center;justify-content:center;z-index:100;padding:20px}
.modal-bg.on{display:flex}
.modal{background:#0e0a22;border:1px solid var(--border-2);border-radius:var(--r-lg);width:100%;max-width:490px;padding:28px;box-shadow:0 24px 70px rgba(0,0,0,0.85);animation:modalIn .32s cubic-bezier(.34,1.56,.64,1);position:relative;overflow:hidden}
.modal::after{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(0,255,213,0.5),rgba(168,85,247,0.5),transparent)}
@keyframes modalIn{0%{transform:scale(.92) translateY(12px);opacity:0}100%{transform:scale(1) translateY(0);opacity:1}}
.modal-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}
.modal-top h3{font-size:18px;font-weight:800;display:flex;align-items:center;gap:10px}
.field{margin-bottom:16px}
.field label{display:block;font-size:12.5px;font-weight:700;color:var(--txt-2);margin-bottom:7px}
.form-control{width:100%;background:rgba(168,85,247,0.06);border:1px solid rgba(168,85,247,0.24);border-radius:12px;padding:12px 16px;color:#fff;font-size:14px;outline:none;font-family:inherit;transition:all .25s;font-weight:500}
.form-control::placeholder{color:var(--txt-3)}
.form-control:focus{border-color:var(--border-hot);background:rgba(0,255,213,0.07);box-shadow:0 0 14px rgba(0,255,213,0.24)}
select.form-control{cursor:pointer;appearance:none;-webkit-appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--txt-2) 50%),linear-gradient(135deg,var(--txt-2) 50%,transparent 50%);background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%;background-size:5px 5px,5px 5px;background-repeat:no-repeat;padding-right:36px}
select.form-control option{background:#0e0a22;color:#fff}
textarea.form-control{resize:vertical;min-height:80px;font-family:'JetBrains Mono',monospace;font-size:12.5px}

/* ============ toast ============ */
.toasts{position:fixed;top:22px;right:22px;z-index:1000;display:flex;flex-direction:column;gap:10px;pointer-events:none;max-width:380px}
.toast{background:rgba(14,10,34,0.96);border:1px solid var(--border-2);border-radius:14px;padding:13px 18px;color:#fff;font-size:13px;font-weight:700;backdrop-filter:blur(14px);box-shadow:0 10px 28px rgba(0,0,0,0.55);display:flex;align-items:center;gap:10px;pointer-events:auto;animation:toastIn .3s ease-out;max-width:100%}
@keyframes toastIn{0%{transform:translateX(60px);opacity:0}100%{transform:translateX(0);opacity:1}}
.toast.success{border-color:rgba(0,255,213,0.55);color:var(--cyan)}
.toast.error{border-color:rgba(244,63,94,0.55);color:var(--rose-2)}
.toast.info{border-color:rgba(59,130,246,0.55);color:var(--blue-2)}
.toast.warning{border-color:rgba(245,158,11,0.55);color:var(--amber-2)}

/* stats tab detail */
.stats-tab-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:16px}
.info-block{background:rgba(0,0,0,0.28);padding:16px;border-radius:14px;border:1px solid rgba(168,85,247,0.14)}
.info-block p{font-size:11.5px;color:var(--txt-2);margin-bottom:8px;text-transform:uppercase;font-weight:700;letter-spacing:.6px}
.info-block h3{font-size:21px;font-weight:800;color:var(--cyan);font-family:'JetBrains Mono',monospace;letter-spacing:-.4px}
.info-block h3.green{color:var(--cyan)}
.info-block h3.violet{color:var(--violet-2)}
.info-block h3.small{font-size:16px}
.info-block .sub{font-size:11px;color:var(--txt-3);margin-top:6px;font-weight:500}

/* ============ mobile ============ */
.m-bar{display:none}
.m-nav{display:none}

@media (max-width:1024px){
  .hero{grid-template-columns:repeat(2,1fr)}
  .workspace{grid-template-columns:1fr}
  .console-panel{height:520px}
}

@media (max-width:768px){
  body{padding-bottom:88px}
  .app{padding:14px}
  .topbar{display:none}
  .m-bar{
    display:flex;align-items:center;justify-content:space-between;gap:10px;
    padding:11px 14px;background:var(--panel);border:1px solid var(--border);
    border-radius:var(--r-md);backdrop-filter:blur(18px);margin-bottom:14px;
    position:sticky;top:10px;z-index:50;box-shadow:var(--shadow);
  }
  .m-brand{display:flex;align-items:center;gap:10px;min-width:0}
  .m-brand .avatar-ring{width:38px;height:38px;padding:2.5px}
  .m-brand .avatar-ring img{border-width:1.5px}
  .m-brand h2{font-size:15px;font-weight:900;background:linear-gradient(90deg,#fff,var(--cyan));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.3px}
  .m-brand .badge-live{font-size:9px;padding:2px 7px;margin-top:2px}
  .m-brand .badge-live .r-dot{width:5px;height:5px}

  .hero{grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
  .stat-card{padding:14px 15px;border-radius:var(--r-md)}
  .stat-data h2{font-size:19px}
  .stat-data p{font-size:10.5px;margin-bottom:5px}
  .stat-badge{font-size:9.5px;padding:2px 7px}
  .s-icon{width:40px;height:40px;font-size:16px;border-radius:12px}

  .mobile-tab{display:none}
  .mobile-tab.on{display:block}
  .mobile-tab.on.console-panel{display:flex}
  .panel{padding:15px;border-radius:var(--r-md)}
  .console-panel{height:calc(100vh - 240px)}
  .accounts{max-height:none}

  .mini-grid{grid-template-columns:repeat(3,1fr);gap:6px}
  .mini-cell{padding:7px 8px}
  .mini-cell .v{font-size:11px}

  .modal-bg{align-items:flex-end;padding:0}
  .modal{max-width:100%;border-radius:26px 26px 0 0;padding:24px 20px 38px;animation:sheetIn .35s cubic-bezier(.34,1.56,.64,1)}
  @keyframes sheetIn{0%{transform:translateY(100%)}100%{transform:translateY(0)}}

  .m-nav{
    position:fixed;bottom:0;left:0;right:0;height:70px;
    background:rgba(7,5,16,0.97);border-top:1px solid var(--border);
    backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
    display:flex;align-items:center;justify-content:space-around;z-index:90;padding:0 8px;
  }
  .mnav-item{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;color:var(--txt-3);font-size:10.5px;font-weight:700;text-decoration:none;background:none;border:none;cursor:pointer;padding:8px 12px;border-radius:12px;font-family:inherit}
  .mnav-item i{font-size:17px}
  .mnav-item.active{color:var(--cyan);background:rgba(0,255,213,0.10);animation:navPop .35s cubic-bezier(.34,1.56,.64,1)}
  @keyframes navPop{0%{transform:scale(.85)}60%{transform:scale(1.08)}100%{transform:scale(1)}}
  .mnav-item .avatar-ring{width:26px;height:26px;padding:2px;animation:none;box-shadow:0 0 10px rgba(168,85,247,0.4)}
  .mnav-item .avatar-ring img{border-width:1.5px}

  .toasts{top:12px;left:14px;right:14px;max-width:none}
  .toast{padding:11px 14px;font-size:12px}
}
</style>
</head>
<body>

<div class="toasts" id="toasts"></div>

<div class="app">

  <!-- ============ DESKTOP TOPBAR ============ -->
  <header class="topbar">
    <div class="brand">
      <div class="avatar-ring" onclick="manualRefresh()" title="malz codex">
        <img src="https://cdn.phototourl.com/member/2026-10-07-da0318ae-9d20-47d8-82b4-0bc72973e9b0.png" alt="malz codex" onerror="this.style.display='none';this.parentNode.style.background='linear-gradient(135deg,#a855f7,#00ffd5)';">
      </div>
      <div class="brand-text">
        <h1>MALZ CODEX <span>| Level Up Command Center</span></h1>
        <div class="brand-sub">
          <span class="badge-live"><span class="r-dot"></span> System Live</span>
          <span class="tagline-chip"><i class="fa-solid fa-bolt" style="color:var(--cyan);font-size:9px"></i> Ultra TCP Gateway</span>
          <span class="tagline-chip"><i class="fa-solid fa-satellite-dish" style="color:var(--violet-2);font-size:9px"></i> OB55 Parallel Engine</span>
        </div>
      </div>
    </div>
    <div class="topbar-right">
      <button class="btn btn-secondary" onclick="manualRefresh()"><i class="fa-solid fa-rotate"></i> Refresh</button>
      <button class="btn btn-primary" onclick="openAddModal()"><i class="fa-solid fa-plus"></i> Add Account</button>
    </div>
  </header>

  <!-- ============ MOBILE APP BAR ============ -->
  <div class="m-bar">
    <div class="m-brand">
      <div class="avatar-ring" onclick="manualRefresh()">
        <img src="https://cdn.phototourl.com/member/2026-10-07-da0318ae-9d20-47d8-82b4-0bc72973e9b0.png" alt="malz codex" onerror="this.style.display='none';this.parentNode.style.background='linear-gradient(135deg,#a855f7,#00ffd5)';">
      </div>
      <div>
        <h2>MALZ CODEX</h2>
        <span class="badge-live"><span class="r-dot"></span> OB55 Live</span>
      </div>
    </div>
    <div style="display:flex;gap:7px">
      <button class="icon-btn" onclick="manualRefresh()" title="Refresh"><i class="fa-solid fa-rotate"></i></button>
      <button class="btn btn-primary" style="padding:8px 12px;font-size:12px" onclick="openAddModal()"><i class="fa-solid fa-plus"></i> Add</button>
    </div>
  </div>

  <!-- ============ HERO STATS ============ -->
  <div class="hero">
    <div class="stat-card c-cyan">
      <div class="stat-data">
        <p>Active Accounts</p>
        <h2 id="st-accounts">0</h2>
        <div class="stat-badge b-cyan" id="st-online-badge"><i class="fa-solid fa-circle-check"></i> 0 Online</div>
      </div>
      <div class="s-icon i-cyan"><i class="fa-solid fa-users"></i></div>
    </div>
    <div class="stat-card c-green">
      <div class="stat-data">
        <p>Total EXP Gained</p>
        <h2 id="st-exp" style="color:var(--cyan)">+0</h2>
        <div class="stat-badge b-green" id="st-rate-badge"><i class="fa-solid fa-gauge-high"></i> ~0 EXP/hr</div>
      </div>
      <div class="s-icon i-green"><i class="fa-solid fa-angles-up"></i></div>
    </div>
    <div class="stat-card c-violet">
      <div class="stat-data">
        <p>Matches Completed</p>
        <h2 id="st-matches">0</h2>
        <div class="stat-badge b-violet" id="st-active-badge"><i class="fa-solid fa-gamepad"></i> 0 In Match</div>
      </div>
      <div class="s-icon i-violet"><i class="fa-solid fa-trophy"></i></div>
    </div>
    <div class="stat-card c-amber">
      <div class="stat-data">
        <p>Bot Uptime</p>
        <h2 id="st-uptime">00:00:00</h2>
        <div class="stat-badge b-amber"><i class="fa-solid fa-shield-halved"></i> 100% Online</div>
      </div>
      <div class="s-icon i-amber"><i class="fa-solid fa-clock"></i></div>
    </div>
  </div>

  <!-- ============ WORKSPACE ============ -->
  <div class="workspace">

    <!-- ACCOUNTS PANEL -->
    <div class="panel mobile-tab on" id="tab-accounts">
      <div class="p-head">
        <div class="p-title">
          <i class="fa-solid fa-user-astronaut" style="color:var(--cyan);font-size:19px"></i>
          <h3>Accounts & EXP Tracker</h3>
          <span class="counter-pill" id="badge-count">0 Loaded</span>
        </div>
        <div class="p-actions">
          <button class="btn-pause-all" id="btn-pause-all" onclick="togglePauseAll()">
            <i class="fa-solid fa-pause"></i> <span>Pause All</span>
          </button>
        </div>
      </div>

      <div class="filter-row">
        <div class="search">
          <i class="fa-solid fa-magnifying-glass"></i>
          <input type="text" id="search-inp" placeholder="Search by Nickname or UID..." oninput="filterAccounts()">
        </div>
        <div class="ftabs">
          <button class="filter-btn active" data-f="all" onclick="setFilter('all',this)">All</button>
          <button class="filter-btn" data-f="in_match" onclick="setFilter('in_match',this)">In Match</button>
          <button class="filter-btn" data-f="online" onclick="setFilter('online',this)">Online</button>
          <button class="filter-btn" data-f="paused" onclick="setFilter('paused',this)">Paused</button>
        </div>
      </div>

      <div class="accounts" id="accounts-box">
        <div class="empty">
          <i class="fa-solid fa-circle-notch fa-spin"></i>
          <p>Connecting to Bot Core...</p>
        </div>
      </div>
    </div>

    <!-- CONSOLE PANEL -->
    <div class="panel console-panel mobile-tab" id="tab-console">
      <div class="p-head">
        <div class="p-title">
          <i class="fa-solid fa-terminal" style="color:var(--cyan);font-size:17px"></i>
          <h3>Live Match Console</h3>
        </div>
        <div class="p-actions">
          <button class="icon-btn" onclick="clearLogs()" title="Clear Console"><i class="fa-solid fa-trash-can"></i></button>
        </div>
      </div>

      <div class="console-tools">
        <div class="cfilter">
          <button class="cpill active" onclick="setLogFilter('all',this)">All</button>
          <button class="cpill" onclick="setLogFilter('match',this)">Matches</button>
          <button class="cpill" onclick="setLogFilter('success',this)">EXP Gained</button>
          <button class="cpill" onclick="setLogFilter('error',this)">Errors</button>
        </div>
        <div class="c-right">
          <button class="toggle-btn active" id="btn-autoscroll" onclick="toggleAutoScroll()">
            <i class="fa-solid fa-arrows-down-to-line"></i> Auto
          </button>
        </div>
      </div>

      <div class="stream" id="stream" onscroll="handleLogScroll()"></div>
      <button class="btn-jump" id="btn-jump" onclick="jumpToBottom()"><i class="fa-solid fa-arrow-down"></i> Latest</button>
    </div>

    <!-- STATS TAB (mobile) -->
    <div class="panel mobile-tab" id="tab-stats">
      <div class="p-head">
        <div class="p-title">
          <i class="fa-solid fa-chart-line" style="color:var(--violet-2);font-size:19px"></i>
          <h3>Performance & Engine Analytics</h3>
        </div>
      </div>

      <div class="stats-tab-grid">
        <div class="stat-card c-cyan">
          <div class="stat-data">
            <p>Active Accounts</p>
            <h2 id="mst-accounts">0</h2>
            <div class="stat-badge b-cyan" id="mst-online-badge"><i class="fa-solid fa-circle-check"></i> 0 Online</div>
          </div>
          <div class="s-icon i-cyan"><i class="fa-solid fa-users"></i></div>
        </div>
        <div class="stat-card c-green">
          <div class="stat-data">
            <p>Total EXP Gained</p>
            <h2 id="mst-exp" style="color:var(--cyan)">+0</h2>
            <div class="stat-badge b-green" id="mst-rate-badge"><i class="fa-solid fa-gauge-high"></i> ~0/hr</div>
          </div>
          <div class="s-icon i-green"><i class="fa-solid fa-angles-up"></i></div>
        </div>
        <div class="stat-card c-violet">
          <div class="stat-data">
            <p>Matches Completed</p>
            <h2 id="mst-matches">0</h2>
            <div class="stat-badge b-violet" id="mst-active-badge"><i class="fa-solid fa-gamepad"></i> 0 In Match</div>
          </div>
          <div class="s-icon i-violet"><i class="fa-solid fa-trophy"></i></div>
        </div>
        <div class="stat-card c-amber">
          <div class="stat-data">
            <p>Bot Uptime</p>
            <h2 id="mst-uptime">00:00:00</h2>
            <div class="stat-badge b-amber"><i class="fa-solid fa-shield-halved"></i> Stable</div>
          </div>
          <div class="s-icon i-amber"><i class="fa-solid fa-clock"></i></div>
        </div>
      </div>

      <div style="display:flex;flex-direction:column;gap:12px">
        <div class="info-block">
          <p>Engine Speed</p>
          <h3 class="green" id="mst-rate">~0 EXP / Hour</h3>
          <div class="sub">Safe multi-match UDP injection rate</div>
        </div>
        <div class="info-block">
          <p>Total Matches Logged</p>
          <h3 class="violet" id="mst-matches-info">0 Matches</h3>
          <div class="sub" id="mst-active-info">0 currently in match</div>
        </div>
        <div class="info-block">
          <p>System Health</p>
          <h3 class="small" style="color:var(--cyan)"><i class="fa-solid fa-shield-halved"></i> 100% Operational</h3>
          <div class="sub">Cloudflare DNS + Persistent Device ID Active</div>
        </div>
      </div>
    </div>

  </div>
</div>

<!-- ============ MOBILE NAV ============ -->
<nav class="m-nav">
  <button class="mnav-item active" onclick="switchMobileTab('accounts',this)">
    <i class="fa-solid fa-user-group"></i>
    <span>Accounts</span>
  </button>
  <button class="mnav-item" onclick="switchMobileTab('stats',this)">
    <i class="fa-solid fa-chart-pie"></i>
    <span>Stats</span>
  </button>
  <button class="mnav-item" onclick="switchMobileTab('console',this)">
    <i class="fa-solid fa-terminal"></i>
    <span>Console</span>
  </button>
  <button class="mnav-item" onclick="openAddModal()">
    <div class="avatar-ring" style="cursor:pointer">
      <img src="https://cdn.phototourl.com/member/2026-10-07-da0318ae-9d20-47d8-82b4-0bc72973e9b0.png" alt="+">
    </div>
    <span>Add</span>
  </button>
</nav>

<!-- ============ ADD MODAL ============ -->
<div class="modal-bg" id="add-modal">
  <div class="modal">
    <div class="modal-top">
      <h3><i class="fa-solid fa-user-plus" style="color:var(--cyan)"></i> Add New Account</h3>
      <button class="icon-btn" onclick="closeAddModal()"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <form id="add-form" onsubmit="submitAddAccount(event)">
      <div class="field">
        <label>Account Login Type</label>
        <select class="form-control" id="acc-type" onchange="toggleFormType()">
          <option value="guest">Guest Account (UID + Password)</option>
          <option value="token">Access Token</option>
        </select>
      </div>
      <div id="guest-inputs">
        <div class="field">
          <label>Guest UID</label>
          <input type="text" class="form-control" id="inp-uid" placeholder="e.g. 7872038363" autocomplete="off">
        </div>
        <div class="field">
          <label>Guest Password / Key</label>
          <input type="text" class="form-control" id="inp-pass" placeholder="e.g. 381002140664..." autocomplete="off">
        </div>
      </div>
      <div id="token-inputs" style="display:none">
        <div class="field">
          <label>Access Token</label>
          <textarea class="form-control" id="inp-token" rows="3" placeholder="Paste access token here..."></textarea>
        </div>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:22px">
        <button type="button" class="btn btn-secondary" onclick="closeAddModal()">Cancel</button>
        <button type="submit" class="btn btn-primary"><i class="fa-solid fa-plus"></i> Save & Start</button>
      </div>
    </form>
  </div>
</div>

<script>
const EXP_TABLE = {
  1:0,2:48,3:202,4:544,5:1012,6:1844,7:2792,8:3800,
  9:4870,10:6004,11:7192,12:8448,13:9760,14:11140,15:12566,
  16:14060,17:15610,18:17224,19:18902,20:20632,21:22424,22:24278,
  23:26192,24:28166,25:30200,26:32294,27:34448,28:37804,29:41274,
  30:44870,31:48582,32:53394,33:58566,34:64096,35:69994,36:76460,
  37:83506,38:91128,39:99322,40:108092,41:120144,42:133266,43:147472,
  44:162760,45:179126,46:196572,47:215368,48:235516,49:257010,50:279860,
  51:304056,52:348318,53:394982,54:444044,55:495508,56:549364,57:633756,
  58:721744,59:813336,60:908522,61:1041438,62:1180352,63:1325266,
  64:1476184,65:1634300,66:1840946,67:2056594,68:2281242,69:2514880,
  70:2757530,71:3059506,72:3372284,73:3699456,74:4041030,75:4397002,
  76:4829104,77:5282204,78:5756304,79:6251408,80:6776502,81:7381324,
  82:8043154,83:8752982,84:9510808,85:10316338,86:11277190,87:12291748,
  88:13360304,89:14482858,90:15659418,91:17026708,92:18453950,93:19941280,
  94:21488570,95:23095858,96:24763138,97:26490428,98:28378704,99:30124996,
  100:32032884
};

let cachedAccounts = [];
let cachedLogs = [];
let autoScrollEnabled = true;
let activeFilter = 'all';
let activeLogFilter = 'all';
const localClientTime = Date.now();

function escapeHtml(text){
  if(text === null || text === undefined) return '';
  return String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function showToast(message, type){
  type = type || 'info';
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  const icon = type === 'success' ? 'fa-circle-check' : (type === 'error' ? 'fa-triangle-exclamation' : (type === 'warning' ? 'fa-circle-exclamation' : 'fa-circle-info'));
  el.innerHTML = '<i class="fa-solid ' + icon + '"></i> <span>' + escapeHtml(message) + '</span>';
  box.appendChild(el);
  setTimeout(function(){
    el.style.opacity = '0';
    el.style.transform = 'translateX(30px)';
    el.style.transition = 'all 0.3s ease';
    setTimeout(function(){ el.remove(); }, 300);
  }, 3400);
}

function openAddModal(){ document.getElementById('add-modal').classList.add('on'); }
function closeAddModal(){ document.getElementById('add-modal').classList.remove('on'); }

function toggleFormType(){
  const t = document.getElementById('acc-type').value;
  document.getElementById('guest-inputs').style.display = t === 'guest' ? 'block' : 'none';
  document.getElementById('token-inputs').style.display = t === 'token' ? 'block' : 'none';
}

async function submitAddAccount(e){
  e.preventDefault();
  const t = document.getElementById('acc-type').value;
  let payload = {};
  if(t === 'guest'){
    const uid = document.getElementById('inp-uid').value.trim();
    const pass = document.getElementById('inp-pass').value.trim();
    if(!uid || !pass){ showToast('UID and Password required', 'error'); return; }
    payload = { uid: uid, password: pass };
  } else {
    const tok = document.getElementById('inp-token').value.trim();
    if(!tok){ showToast('Access token required', 'error'); return; }
    payload = { token: tok };
  }
  try {
    const r = await fetch('/api/account/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if(d.status === 'ok'){
      closeAddModal();
      document.getElementById('add-form').reset();
      toggleFormType();
      showToast('Account added and worker scheduled', 'success');
      fetchStats();
    } else {
      showToast('Failed: ' + (d.error || 'Unknown'), 'error');
    }
  } catch(err){
    showToast('Network error adding account', 'error');
  }
}

async function deleteAccount(uid, authUid){
  if(!confirm('Permanently remove account UID ' + uid + ' ?')) return;
  try {
    const r = await fetch('/api/account/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uid: uid, auth_uid: authUid || '' })
    });
    const d = await r.json();
    if(d.status === 'ok'){
      showToast('Account ' + uid + ' removed', 'info');
      fetchStats();
    } else {
      showToast('Error: ' + (d.error || 'Unknown'), 'error');
    }
  } catch(err){
    showToast('Network error during deletion', 'error');
  }
}

async function refreshAccountInfo(uid){
  try {
    showToast('Refreshing profile ' + uid + '...', 'info');
    await fetch('/api/account/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uid: uid })
    });
    setTimeout(fetchStats, 900);
  } catch(err){
    showToast('Failed to refresh', 'error');
  }
}

async function restartAccount(uid){
  try {
    showToast('Restarting worker ' + uid + '...', 'info');
    await fetch('/api/account/restart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uid: uid })
    });
    setTimeout(fetchStats, 900);
  } catch(err){
    showToast('Failed to restart', 'error');
  }
}

async function clearLogs(){
  try {
    await fetch('/api/logs/clear', { method: 'POST' });
    cachedLogs = [];
    document.getElementById('stream').innerHTML = '';
    showToast('Console cleared', 'info');
  } catch(err){
    showToast('Failed to clear logs', 'error');
  }
}

function copyUid(uid){
  const txt = String(uid);
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(txt).then(function(){
      showToast('Copied UID ' + txt, 'success');
    }).catch(function(){
      showToast('UID: ' + txt, 'info');
    });
  } else {
    showToast('UID: ' + txt, 'info');
  }
}

function manualRefresh(){
  fetchStats();
  showToast('Stats refreshed', 'info');
}

function setFilter(filter, btn){
  activeFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  filterAccounts();
}

function formatDuration(sec){
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if(h > 0){
    return h + 'h ' + String(m).padStart(2,'0') + 'm ' + String(s).padStart(2,'0') + 's';
  }
  return String(m).padStart(2,'0') + 'm ' + String(s).padStart(2,'0') + 's';
}

async function togglePauseAccount(uid){
  try {
    const r = await fetch('/api/account/pause', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uid: uid })
    });
    const d = await r.json();
    if(d.status === 'ok'){
      showToast(d.is_paused ? 'Paused ' + uid : 'Resumed ' + uid, d.is_paused ? 'warning' : 'success');
      fetchStats();
    } else {
      showToast(d.error || 'Failed', 'error');
    }
  } catch(err){
    showToast('Network error toggling pause', 'error');
  }
}

async function togglePauseAll(){
  try {
    const r = await fetch('/api/account/pause_all', { method: 'POST' });
    const d = await r.json();
    if(d.status === 'ok'){
      showToast(d.all_paused ? 'All accounts PAUSED' : 'All accounts RESUMED', d.all_paused ? 'warning' : 'success');
      fetchStats();
    } else {
      showToast(d.error || 'Failed', 'error');
    }
  } catch(err){
    showToast('Network error', 'error');
  }
}

function filterAccounts(){
  const q = (document.getElementById('search-inp').value || '').toLowerCase().trim();
  document.querySelectorAll('.acc-card').forEach(function(card){
    const uid = (card.dataset.uid || '').toLowerCase();
    const nick = (card.dataset.nick || '').toLowerCase();
    const st = (card.dataset.status || '').toLowerCase();
    const paused = card.dataset.isPaused === '1';
    const matchQ = !q || uid.indexOf(q) !== -1 || nick.indexOf(q) !== -1;
    let matchF = true;
    if(activeFilter === 'in_match'){
      matchF = (st.indexOf('in_match') !== -1 || st.indexOf('match') !== -1) && !paused;
    } else if(activeFilter === 'online'){
      matchF = (st.indexOf('online') !== -1 || st.indexOf('searching') !== -1) && !paused;
    } else if(activeFilter === 'paused'){
      matchF = paused || st.indexOf('paused') !== -1;
    }
    card.style.display = (matchQ && matchF) ? '' : 'none';
  });
}

function switchMobileTab(tabName, btn){
  document.querySelectorAll('.mnav-item').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  const ta = document.getElementById('tab-accounts');
  const ts = document.getElementById('tab-stats');
  const tc = document.getElementById('tab-console');
  ta.classList.remove('on');
  ts.classList.remove('on');
  tc.classList.remove('on');
  if(tabName === 'accounts') ta.classList.add('on');
  else if(tabName === 'stats') ts.classList.add('on');
  else if(tabName === 'console'){
    tc.classList.add('on');
    if(autoScrollEnabled) jumpToBottom();
  }
}

function setLogFilter(filter, btn){
  activeLogFilter = filter;
  document.querySelectorAll('.cpill').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  renderLogs(cachedLogs);
}

function toggleAutoScroll(){
  autoScrollEnabled = !autoScrollEnabled;
  const btn = document.getElementById('btn-autoscroll');
  if(autoScrollEnabled){
    btn.classList.add('active');
    jumpToBottom();
  } else {
    btn.classList.remove('active');
  }
}

function handleLogScroll(){
  const s = document.getElementById('stream');
  const nearBottom = s.scrollHeight - s.scrollTop - s.clientHeight < 60;
  const jb = document.getElementById('btn-jump');
  jb.style.display = nearBottom ? 'none' : 'block';
}

function jumpToBottom(){
  const s = document.getElementById('stream');
  s.scrollTop = s.scrollHeight;
  const jb = document.getElementById('btn-jump');
  if(jb) jb.style.display = 'none';
}

function renderAccounts(accounts){
  const box = document.getElementById('accounts-box');
  document.getElementById('badge-count').innerText = accounts.length + ' Active';

  const allPaused = accounts.length > 0 && accounts.every(function(a){ return a.is_paused || a.status === 'PAUSED'; });
  const gb = document.getElementById('btn-pause-all');
  if(gb){
    if(allPaused){
      gb.className = 'btn-pause-all all-paused';
      gb.innerHTML = '<i class="fa-solid fa-play"></i> <span>Resume All</span>';
    } else {
      gb.className = 'btn-pause-all';
      gb.innerHTML = '<i class="fa-solid fa-pause"></i> <span>Pause All</span>';
    }
  }

  if(accounts.length === 0){
    box.innerHTML = '<div class="empty"><i class="fa-solid fa-ghost"></i><p>No active accounts running. Click "+ Add Account" to start farming.</p><button class="btn btn-primary" onclick="openAddModal()"><i class="fa-solid fa-plus"></i> Add First Account</button></div>';
    return;
  }
  if(box.querySelector('.empty')) box.innerHTML = '';

  const currentUids = {};
  accounts.forEach(function(a){ currentUids[String(a.uid)] = 1; });

  box.querySelectorAll('.acc-card').forEach(function(card){
    if(!currentUids[card.dataset.uid]) card.remove();
  });

  accounts.forEach(function(acc){
    const uid = String(acc.uid);
    const gained = acc.gained_exp || 0;
    const isPaused = Boolean(acc.is_paused || acc.status === 'PAUSED');
    const uptimeSec = Math.floor(acc.uptime_seconds || 0);
    const status = isPaused ? 'PAUSED' : (acc.status || 'ONLINE');
    let statusClass = 'online';
    if(isPaused) statusClass = 'paused';
    else if(status === 'IN_MATCH') statusClass = 'in_match';
    else if(status === 'SEARCHING') statusClass = 'searching';
    else if(status === 'ONLINE') statusClass = 'online';
    else statusClass = 'error';

    const statusText = isPaused ? 'PAUSED' : (status === 'IN_MATCH' ? ('IN MATCH (' + (acc.active_matches || 1) + ')') : status);

    const lvl = Math.max(1, parseInt(acc.level) || 1);
    const nextLvl = Math.min(100, lvl + 1);
    const baseExp = EXP_TABLE[lvl] !== undefined ? EXP_TABLE[lvl] : 0;
    const targetExp = EXP_TABLE[nextLvl] !== undefined ? EXP_TABLE[nextLvl] : (baseExp + 50000);
    const needed = Math.max(1, targetExp - baseExp);
    const earned = Math.max(0, acc.current_exp - baseExp);
    const remain = Math.max(0, targetExp - acc.current_exp);
    const pct = lvl >= 100 ? 100 : Math.min(100, Math.max(0, (earned / needed) * 100));

    const initial = String(acc.nickname || 'P').trim().charAt(0).toUpperCase() || 'P';
    const nickname = escapeHtml(acc.nickname || 'Player');
    const region = escapeHtml(acc.region || 'BD');
    const modeLabel = lvl < 3 ? 'BR (Lvl < 3)' : 'Lone Wolf (Lvl 3+)';
    const modeIcon = lvl < 3 ? 'fa-crosshairs' : 'fa-shield-halved';
    const modeClass = lvl < 3 ? 'br' : 'lw';

    const matches = acc.matches_played || 0;
    const activeM = acc.active_matches || 0;
    const likes = (acc.likes || 0).toLocaleString();
    const lastMatch = acc.last_match_time || '—';

    let card = document.getElementById('acc-card-' + uid);
    if(!card){
      card = document.createElement('div');
      card.id = 'acc-card-' + uid;
      card.className = 'acc-card';
      card.dataset.uid = uid;
      box.appendChild(card);
    }

    card.dataset.nick = acc.nickname || '';
    card.dataset.status = statusClass;
    card.dataset.isPaused = isPaused ? '1' : '0';

    card.innerHTML =
      '<div class="acc-head">' +
        '<div class="acc-id">' +
          '<div class="acc-avatar">' + initial +
            '<span class="level-badge">L' + lvl + '</span>' +
          '</div>' +
          '<div class="acc-meta">' +
            '<div class="acc-name">' + nickname +
              ' <span class="region-tag">' + region + '</span>' +
              ' <span class="mode-badge ' + modeClass + '"><i class="fa-solid ' + modeIcon + '"></i> ' + modeLabel + '</span>' +
            '</div>' +
            '<div class="acc-uid-line">' +
              '<span class="acc-uid">UID: ' + escapeHtml(uid) + '</span>' +
              '<button class="btn-copy" onclick="copyUid(\'' + uid + '\')" title="Copy UID"><i class="fa-regular fa-copy"></i></button>' +
              '<span class="uptime-pill ' + (isPaused ? 'paused' : '') + '" title="In-Game Playtime Uptime">' +
                '<i class="fa-solid fa-stopwatch"></i>' +
                '<span class="uptime-val" data-uid="' + uid + '" data-uptime="' + uptimeSec + '" data-paused="' + (isPaused ? '1' : '0') + '">' + formatDuration(uptimeSec) + '</span>' +
              '</span>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="status-pill ' + statusClass + '"><span class="r-dot"></span><span>' + escapeHtml(statusText) + '</span></div>' +
      '</div>' +

      '<div class="exp-strip">' +
        '<div class="exp-col"><span>Initial</span><strong>' + (acc.initial_exp || 0).toLocaleString() + '</strong></div>' +
        '<div class="exp-col"><span>Current</span><strong>' + (acc.current_exp || 0).toLocaleString() + '</strong></div>' +
        '<div class="exp-col"><span>Session</span><strong class="gain">+' + gained.toLocaleString() + '</strong></div>' +
      '</div>' +

      '<div class="progress-box">' +
        '<div class="prog-top">' +
          '<span class="prog-tag"><i class="fa-solid fa-angles-up" style="color:var(--cyan)"></i> Level ' + lvl + ' &rarr; <strong>L' + nextLvl + '</strong></span>' +
          '<span class="prog-need"><i class="fa-solid fa-bolt"></i> ' + remain.toLocaleString() + ' EXP needed</span>' +
        '</div>' +
        '<div class="prog-track" title="Level ' + lvl + ': ' + earned.toLocaleString() + ' / ' + needed.toLocaleString() + ' EXP (' + pct.toFixed(1) + '%)">' +
          '<div class="prog-fill" style="width:' + pct.toFixed(1) + '%"></div>' +
        '</div>' +
        '<div class="prog-bot">' +
          '<span>' + earned.toLocaleString() + ' / ' + needed.toLocaleString() + ' EXP</span>' +
          '<span class="pct-pill">' + pct.toFixed(1) + '%</span>' +
        '</div>' +
      '</div>' +

      '<div class="mini-grid">' +
        '<div class="mini-cell"><span class="k">Matches</span><span class="v matches">' + matches + '</span></div>' +
        '<div class="mini-cell"><span class="k">Last Match</span><span class="v last">' + escapeHtml(lastMatch) + '</span></div>' +
        '<div class="mini-cell"><span class="k">Likes</span><span class="v likes">' + likes + '</span></div>' +
      '</div>' +

      '<div class="acc-foot">' +
        '<span class="acc-foot-label"><i class="fa-solid fa-tower-broadcast" style="color:var(--cyan);font-size:10px"></i> Active: ' + activeM + ' &nbsp;|&nbsp; Total: ' + matches + '</span>' +
        '<div class="acc-btns">' +
          '<button class="icon-btn ' + (isPaused ? 'btn-resume' : 'btn-pause') + '" onclick="togglePauseAccount(\'' + uid + '\')" title="' + (isPaused ? 'Resume' : 'Pause') + '"><i class="fa-solid ' + (isPaused ? 'fa-play' : 'fa-pause') + '"></i></button>' +
          '<button class="icon-btn" onclick="restartAccount(\'' + uid + '\')" title="Restart Worker"><i class="fa-solid fa-arrow-rotate-right"></i></button>' +
          '<button class="icon-btn" onclick="refreshAccountInfo(\'' + uid + '\')" title="Refresh Profile EXP"><i class="fa-solid fa-arrows-rotate"></i></button>' +
          '<button class="icon-btn danger" onclick="deleteAccount(\'' + uid + '\', \'' + escapeHtml(acc.auth_uid || '') + '\')" title="Delete Account"><i class="fa-solid fa-trash"></i></button>' +
        '</div>' +
      '</div>';
  });

  filterAccounts();
}

function renderLogs(logs){
  const stream = document.getElementById('stream');
  let filtered = logs;
  if(activeLogFilter === 'match'){
    filtered = logs.filter(function(l){ return l.message.indexOf('Match') !== -1 || l.message.indexOf('⚔') !== -1; });
  } else if(activeLogFilter === 'success'){
    filtered = logs.filter(function(l){ return l.level === 'success' || l.message.indexOf('EXP') !== -1; });
  } else if(activeLogFilter === 'error'){
    filtered = logs.filter(function(l){ return l.level === 'error' || l.level === 'warning'; });
  }

  const icons = {
    info: 'fa-circle-info',
    success: 'fa-circle-check',
    warning: 'fa-triangle-exclamation',
    error: 'fa-circle-xmark'
  };

  stream.innerHTML = filtered.map(function(log){
    const lv = log.level || 'info';
    const ic = icons[lv] || icons.info;
    return '<div class="log-e">' +
      '<span class="log-ts">[' + escapeHtml(log.time || '00:00:00') + ']</span>' +
      '<i class="fa-solid ' + ic + ' log-icon ' + lv + '"></i>' +
      '<span class="log-txt ' + lv + '">' + escapeHtml(log.message) + '</span>' +
    '</div>';
  }).join('');

  if(autoScrollEnabled) jumpToBottom();
}

function setText(id, val){
  const el = document.getElementById(id);
  if(el) el.innerText = (val !== undefined && val !== null) ? val : '';
}
function setHtml(id, val){
  const el = document.getElementById(id);
  if(el) el.innerHTML = (val !== undefined && val !== null) ? val : '';
}

async function fetchStats(){
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();

    const onlineCount = d.accounts.filter(function(a){ return a.status === 'ONLINE' || a.status === 'IN_MATCH'; }).length;
    const expStr = '+' + d.total_gained_exp.toLocaleString();
    const rateStr = '~' + (d.exp_per_hour || 0).toLocaleString() + ' EXP/hr';

    // desktop hero
    setText('st-accounts', d.total_accounts);
    setText('st-exp', expStr);
    setText('st-matches', d.total_matches);
    setHtml('st-online-badge', '<i class="fa-solid fa-circle-check"></i> ' + onlineCount + ' Online');
    setHtml('st-rate-badge', '<i class="fa-solid fa-gauge-high"></i> ' + rateStr);
    setHtml('st-active-badge', '<i class="fa-solid fa-gamepad"></i> ' + (d.total_active_matches || 0) + ' In Match');

    // mobile stats
    setText('mst-accounts', d.total_accounts);
    setText('mst-exp', expStr);
    setText('mst-matches', d.total_matches);
    setHtml('mst-online-badge', '<i class="fa-solid fa-circle-check"></i> ' + onlineCount + ' Online');
    setHtml('mst-rate-badge', '<i class="fa-solid fa-gauge-high"></i> ~' + (d.exp_per_hour || 0).toLocaleString() + '/hr');
    setHtml('mst-active-badge', '<i class="fa-solid fa-gamepad"></i> ' + (d.total_active_matches || 0) + ' In Match');

    setText('mst-rate', '~' + (d.exp_per_hour || 0).toLocaleString() + ' EXP / Hour');
    setText('mst-matches-info', d.total_matches + ' Matches');
    setText('mst-active-info', (d.total_active_matches || 0) + ' currently in match');

    cachedAccounts = d.accounts;
    renderAccounts(d.accounts);

    cachedLogs = d.logs;
    renderLogs(d.logs);
  } catch(err){
    console.warn('Stats poll error:', err);
  }
}

// uptime ticker
setInterval(function(){
  const sec = Math.floor((Date.now() - localClientTime) / 1000);
  const hh = String(Math.floor(sec / 3600)).padStart(2,'0');
  const mm = String(Math.floor((sec % 3600) / 60)).padStart(2,'0');
  const ss = String(sec % 60).padStart(2,'0');
  const upStr = hh + ':' + mm + ':' + ss;
  setText('st-uptime', upStr);
  setText('mst-uptime', upStr);

  document.querySelectorAll('.uptime-val').forEach(function(el){
    if(el.dataset.paused !== '1'){
      const cur = parseInt(el.dataset.uptime || '0', 10) + 1;
      el.dataset.uptime = cur;
      el.innerText = formatDuration(cur);
    }
  });
}, 1000);

// initial + polling
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