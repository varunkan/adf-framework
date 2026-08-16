#!/usr/bin/env python3
"""Run a built APK on a CLEAN, dedicated Android emulator and screenshot it — the
"see it in an emulator" half of ADF's mobile delivery, as a decision ADF owns.

NEVER the user's dev device: ADF picks a running emulator that has room (>[minFreeMB]
free on /data), and only boots a fresh AVD if none qualifies — so a build can never
fail to install over (or disturb) an unrelated app the way it would on a full dev
emulator. Installs the APK as its OWN package (com.adf.<feature>), launches it, and
captures a device screenshot for the Studio preview.

Gated: returns (False, reason, None) gracefully when no emulator/AVD is available, so
the deterministic / offline path degrades like the iOS render. Set
ADF_ANDROID_EMULATOR=strict to require it.

Returns (ok: bool, detail: str, screenshot_path | None).
"""
import os
import re
import subprocess
import time

from mobile_build import android_sdk, package_id


def _adb(args, serial=None, timeout=60):
    cmd = ["adb"] + (["-s", serial] if serial else []) + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          env=_env())


def _env():
    sdk = android_sdk()
    env = dict(os.environ)
    if sdk:
        env["ANDROID_HOME"] = sdk
        env["ANDROID_SDK_ROOT"] = sdk
        env["PATH"] = f"{sdk}/platform-tools:{sdk}/emulator:" + env.get("PATH", "")
    return env


def running_emulators():
    """Serials of online emulators."""
    try:
        out = _adb(["devices"]).stdout
    except Exception:
        return []
    return [ln.split("\t")[0] for ln in out.splitlines()
            if ln.startswith("emulator-") and "\tdevice" in ln]


def list_avds():
    try:
        out = subprocess.run(["emulator", "-list-avds"], capture_output=True,
                             text=True, timeout=20, env=_env()).stdout
        return [a.strip() for a in out.splitlines() if a.strip()]
    except Exception:
        return []


def _free_mb(serial):
    """Free MB on /data for an emulator, or -1."""
    try:
        out = _adb(["shell", "df", "/data"], serial=serial).stdout.strip().splitlines()
        return int(out[-1].split()[3]) // 1024 if out else -1
    except Exception:
        return -1


def pick_clean_device(min_free_mb=800):
    """A running emulator with enough room, or None. The 'don't use the user's full
    dev device' decision: a device at 94% full is skipped, not overwritten."""
    best, best_free = None, -1
    for s in running_emulators():
        if _adb(["shell", "getprop", "sys.boot_completed"],
                serial=s).stdout.strip() != "1":
            continue
        free = _free_mb(s)
        if free >= min_free_mb and free > best_free:
            best, best_free = s, free
    return best


def _boot_avd(timeout=180):
    """Boot a fresh preview AVD and return its serial once booted, or None."""
    avds = list_avds()
    if not avds:
        return None
    before = set(running_emulators())
    try:
        subprocess.Popen(["emulator", "-avd", avds[0], "-no-snapshot-load",
                          "-no-boot-anim"], env=_env(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        new = [s for s in running_emulators() if s not in before]
        for s in new:
            if _adb(["shell", "getprop", "sys.boot_completed"],
                    serial=s).stdout.strip() == "1":
                return s
        time.sleep(4)
    return None


def preview(apk_path, feature_id, app_root=None, settle_secs=12, log=print):
    """Install [apk_path] on a clean emulator, launch it, and screenshot. Returns
    (ok, detail, screenshot_path)."""
    strict = os.environ.get("ADF_ANDROID_EMULATOR", "").lower() == "strict"
    if not apk_path or not os.path.isfile(apk_path):
        return (False, "no APK to preview", None)
    if android_sdk() is None:
        return (False, "no Android SDK — emulator preview skipped", None)

    serial = pick_clean_device()
    if serial is None:
        log("mobile: no clean emulator running — booting a dedicated preview AVD…")
        serial = _boot_avd()
    if serial is None:
        msg = ("no Android emulator available with room (and no AVD to boot) — "
               "preview skipped; open one or set ADF_ANDROID_EMULATOR=strict")
        return (False if strict else True, msg, None)

    pkg = package_id(feature_id)
    inst = _adb(["install", "-r", apk_path], serial=serial, timeout=180)
    if "Success" not in (inst.stdout + inst.stderr):
        return (False, "install failed on emulator:\n"
                + (inst.stdout + inst.stderr)[-600:], None)
    _adb(["shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"],
         serial=serial)
    time.sleep(settle_secs)

    # Screenshot for the Studio preview. `screencap -p` emits raw PNG bytes, so
    # write them straight to the file — a text-mode adb call would corrupt them.
    shot = None
    if app_root:
        try:
            vdir = os.path.join(app_root, ".adf-mobile")
            os.makedirs(vdir, exist_ok=True)
            cand = os.path.join(vdir, "android-preview.png")
            with open(cand, "wb") as f:
                subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"],
                               stdout=f, timeout=30, env=_env())
            if os.path.getsize(cand) > 1000:
                shot = cand
        except Exception:
            shot = None

    return (True, f"installed {pkg} on {serial} and launched"
            + (" (screenshot captured)" if shot else ""), shot)
