#!/usr/bin/env python3
"""Standalone native APK build for ADF's Expo (react-native) stack — the build
decisions ADF OWNS, so no one hand-cranks a mobile build again.

Given a generated Expo app dir, produce an installable, self-contained release APK:

  1. native ids — managed Expo has no `android.package` / `ios.bundleIdentifier`,
     but `expo prebuild` requires them. Derive `com.adf.<feature>` (never the host
     app's id, so it installs as a SEPARATE app) and inject it.
  2. SMART strip — remove feature-optional NATIVE modules the app never imports
     (e.g. a calculator that never touches a DB drops `expo-sqlite`). Smaller APK
     and, critically, avoids native (CMake/Gradle) build failures from modules
     nothing uses — "don't build what you don't use."
  3. single ABI (arm64-v8a) — matches the emulator, ~4x smaller, dodges the
     multi-ABI CMake race.
  4. `expo prebuild` + gradle `assembleRelease` (debug-keystore signed →
     sideloadable, no Play account needed).

Gated: returns (False, reason, None) when the Android toolchain (SDK + java) is
absent — exactly like the iOS render degrades — so the deterministic / offline path
never hard-fails on a machine without Android tooling.

Returns (ok: bool, detail: str, apk_path: str | None).
"""
import json
import os
import re
import shutil
import subprocess

# Feature-optional native modules: present in the template for data-backed apps,
# but a calculator/timer/etc. that never imports them shouldn't pay the native
# build cost (and expo-sqlite's CMake build is the one that fails when unused).
# Core modules (expo-router, expo-modules-core, react-native, …) are NEVER stripped.
STRIPPABLE_NATIVE = ("expo-sqlite",)

ANDROID_ABI = "arm64-v8a"


def android_sdk():
    """The Android SDK dir, or None. Honors ANDROID_HOME / ANDROID_SDK_ROOT, then the
    macOS default. Gating signal for the whole native build."""
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        p = os.environ.get(env)
        if p and os.path.isdir(p):
            return p
    default = os.path.expanduser("~/Library/Android/sdk")
    return default if os.path.isdir(default) else None


def _java_ok():
    try:
        subprocess.run(["java", "-version"], capture_output=True, timeout=15)
        return True
    except Exception:
        return shutil.which("java") is not None


def native_toolchain_ready():
    """True iff an Android APK can be built here (SDK + java). The gate."""
    return android_sdk() is not None and _java_ok()


def package_id(feature_id):
    """A valid, collision-proof Android package / iOS bundle id for the feature —
    `com.adf.<sanitized>`. Never the host app's id, so the build installs as its own
    separate app and can never overwrite an unrelated app on the device."""
    slug = re.sub(r"[^a-z0-9]", "", (feature_id or "app").lower()) or "app"
    return f"com.adf.{slug}"


def _ensure_native_ids(app_dir, feature_id):
    """Inject the package id + a human app name into app.json (prebuild needs them)."""
    p = os.path.join(app_dir, "app.json")
    with open(p, encoding="utf-8") as f:
        cfg = json.load(f)
    exp = cfg.get("expo", cfg)
    pkg = package_id(feature_id)
    name = (feature_id or "app").replace("-", " ").replace("_", " ").title()
    exp["name"] = name
    exp.setdefault("android", {})["package"] = pkg
    exp.setdefault("ios", {})["bundleIdentifier"] = pkg
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return pkg, name


def _source_text(app_dir):
    """All app source (app/, src/) concatenated — to decide which optional native
    modules are actually imported."""
    chunks = []
    for sub in ("app", "src"):
        d = os.path.join(app_dir, sub)
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for fn in files:
                if fn.endswith((".ts", ".tsx", ".js", ".jsx")):
                    try:
                        with open(os.path.join(root, fn), encoding="utf-8",
                                  errors="ignore") as f:
                            chunks.append(f.read())
                    except OSError:
                        pass
    return "\n".join(chunks)


def _imports(src, mod):
    """Does the source import `mod` (es-import or require)?"""
    m = re.escape(mod)
    return bool(re.search(rf"""from\s+['"]{m}['"]""", src)
                or re.search(rf"""require\(\s*['"]{m}['"]""", src))


def strip_unused_native(app_dir):
    """Remove feature-optional native modules the app never imports — from
    package.json AND node_modules (so Expo autolinking won't build them). Returns the
    list stripped. This is the 'don't build what you don't use' decision ADF owns."""
    src = _source_text(app_dir)
    pkg_path = os.path.join(app_dir, "package.json")
    with open(pkg_path, encoding="utf-8") as f:
        pkg = json.load(f)
    stripped = []
    for mod in STRIPPABLE_NATIVE:
        if _imports(src, mod):
            continue
        removed = False
        for sec in ("dependencies", "devDependencies"):
            if pkg.get(sec, {}).pop(mod, None) is not None:
                removed = True
        nm = os.path.join(app_dir, "node_modules", mod)
        if os.path.isdir(nm):
            shutil.rmtree(nm, ignore_errors=True)
            removed = True
        if removed:
            stripped.append(mod)
    if stripped:
        with open(pkg_path, "w", encoding="utf-8") as f:
            json.dump(pkg, f, indent=2)
    return stripped


def _native_env():
    sdk = android_sdk()
    env = dict(os.environ)
    if sdk:
        env["ANDROID_HOME"] = sdk
        env["ANDROID_SDK_ROOT"] = sdk
        env["PATH"] = f"{sdk}/platform-tools:{sdk}/emulator:" + env.get("PATH", "")
    return env


def build_apk(app_dir, feature_id, timeout=1200, log=print):
    """Build a standalone, signed release APK for [feature_id] from the Expo app at
    [app_dir]. Returns (ok, detail, apk_path). Gated on the Android toolchain."""
    if not native_toolchain_ready():
        return (False, "android toolchain absent (no Android SDK / java) — native APK "
                       "skipped; set ANDROID_HOME or install the SDK to enable", None)
    if not os.path.isfile(os.path.join(app_dir, "app.json")):
        return (False, "not an Expo app (no app.json) — native APK skipped", None)

    env = _native_env()
    pkg, name = _ensure_native_ids(app_dir, feature_id)
    stripped = strip_unused_native(app_dir)
    log(f"mobile: building {name} ({pkg})"
        + (f"; stripped unused native: {', '.join(stripped)}" if stripped else ""))

    # Clean prebuild: regenerate the native project with the new id + pruned deps.
    for d in ("android", "ios"):
        shutil.rmtree(os.path.join(app_dir, d), ignore_errors=True)
    try:
        r = subprocess.run(
            ["npx", "expo", "prebuild", "--platform", "android", "--no-install"],
            cwd=app_dir, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return (False, f"expo prebuild error: {e}", None)
    if r.returncode != 0 or not os.path.isdir(os.path.join(app_dir, "android")):
        return (False, "expo prebuild failed:\n"
                + (r.stderr or r.stdout or "")[-1500:], None)

    # Single ABI for the emulator target (small + fast + race-free).
    gp = os.path.join(app_dir, "android", "gradle.properties")
    try:
        s = open(gp, encoding="utf-8").read()
        s = (re.sub(r"reactNativeArchitectures=.*",
                    f"reactNativeArchitectures={ANDROID_ABI}", s)
             if "reactNativeArchitectures" in s
             else s + f"\nreactNativeArchitectures={ANDROID_ABI}\n")
        open(gp, "w", encoding="utf-8").write(s)
    except OSError:
        pass

    try:
        subprocess.run(["./gradlew", "assembleRelease", "--no-daemon", "-q"],
                       cwd=os.path.join(app_dir, "android"), capture_output=True,
                       text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return (False, f"gradle assembleRelease error: {e}", None)

    rel = os.path.join(app_dir, "android", "app", "build", "outputs", "apk", "release")
    apks = ([os.path.join(rel, f) for f in os.listdir(rel) if f.endswith(".apk")]
            if os.path.isdir(rel) else [])
    if not apks:
        return (False, "gradle produced no release APK (assembleRelease failed)", None)

    # Publish a stable, feature-named copy into the app for download + sealing.
    dest = os.path.join(app_dir, ".adf-mobile", f"{feature_id}.apk")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(apks[0], dest)
    mb = os.path.getsize(dest) // (1024 * 1024)
    detail = f"{name} ({pkg}) → {feature_id}.apk ({mb}MB, arm64-v8a, signed)"
    if stripped:
        detail += f"; stripped: {', '.join(stripped)}"
    return (True, detail, dest)
