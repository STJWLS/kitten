# -*- coding: utf-8 -*-
"""KittenPuppy4Ever native Android APK builder (no Gradle, pure SDK tools).

Flow: aapt2 -> javac -> d8 -> inject dex -> zipalign -> apksigner.

Local prerequisites are the existing app/toolchain (JDK17 + Android SDK 34).
CI can provide JAVA_HOME / ANDROID_SDK_ROOT instead.
"""
import os, shutil, subprocess, sys, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.join(HERE, "KittenPuppy")
SRC = os.path.join(APP_ROOT, "app", "src", "main")
TOOLCHAIN = os.path.join(HERE, "..", "app", "toolchain")
RELEASES = os.path.join(HERE, "..", "releases")

def _jdk():
    candidates = [os.environ.get("JAVA_HOME"), os.environ.get("JDK_HOME")]
    if os.path.isdir(TOOLCHAIN):
        for d in sorted(os.listdir(TOOLCHAIN)):
            p = os.path.join(TOOLCHAIN, d)
            if os.path.isdir(p) and d.startswith("jdk"):
                candidates.append(p)
    for p in candidates:
        if p and os.path.isfile(os.path.join(p, "bin", "javac.exe" if os.name == "nt" else "javac")):
            return p
    return None

def _sdk():
    for env in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        p = os.environ.get(env)
        if p and os.path.isdir(os.path.join(p, "build-tools")):
            return p
    p = os.path.join(TOOLCHAIN, "android-sdk")
    return p if os.path.isdir(os.path.join(p, "build-tools")) else None

JDK = _jdk()
SDK = _sdk()
if not JDK:
    raise SystemExit("未找到 JDK：设置 JAVA_HOME 或放入 app/toolchain/jdk-*")
if not SDK:
    raise SystemExit("未找到 Android SDK：设置 ANDROID_SDK_ROOT/ANDROID_HOME 或放入 app/toolchain/android-sdk")
BT = os.path.join(SDK, "build-tools", sorted(os.listdir(os.path.join(SDK, "build-tools")))[-1])
PLATFORM = os.path.join(SDK, "platforms", sorted(os.listdir(os.path.join(SDK, "platforms")))[-1])
ANDROID_JAR = os.path.join(PLATFORM, "android.jar")
BUILD_DIR = os.path.join(APP_ROOT, "build")
KEYSTORE = os.path.join(APP_ROOT, "kp.keystore")
KS_PASS = os.environ.get("KP_KS_PASS", "kp2026")
ALIAS = "kittenpuppy"
APP_NAME = "KittenPuppy4Ever"
VERSION = "0.4.0"
OUT_APK = os.path.join(RELEASES, APP_NAME + "-" + VERSION + ".apk")

def jdk_bin(tool):
    return os.path.join(JDK, "bin", tool + (".exe" if os.name == "nt" else ""))

def bt_bin(tool):
    if os.name == "nt":
        ext = ".bat" if tool in ("d8", "apksigner") else ".exe"
    else:
        ext = ""
    return os.path.join(BT, tool + ext)

def run(cmd, **kw):
    print("  $", " ".join(cmd) if not isinstance(cmd, str) else cmd)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        print(r.stdout[-4000:]); print(r.stderr[-4000:])
        raise SystemExit("命令失败（%d）" % r.returncode)
    return r

def main():
    os.environ["JAVA_HOME"] = JDK
    os.makedirs(BUILD_DIR, exist_ok=True); os.makedirs(RELEASES, exist_ok=True)
    for f in os.listdir(BUILD_DIR):
        p = os.path.join(BUILD_DIR, f)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)

    print("[1/7] aapt2 compile")
    compiled = os.path.join(BUILD_DIR, "compiled"); os.makedirs(compiled, exist_ok=True)
    res_root = os.path.join(SRC, "res")
    for root, _dirs, files in os.walk(res_root):
        for f in files:
            if f.endswith((".xml", ".png")):
                src = os.path.join(root, f)
                rel = os.path.relpath(src, res_root).replace(os.sep, "-")
                run([bt_bin("aapt2"), "compile", src, "-o", os.path.join(compiled, rel + ".flata")])
    flata = [os.path.join(compiled, f) for f in os.listdir(compiled) if f.endswith(".flata")]

    print("[2/7] aapt2 link")
    gen_dir = os.path.join(BUILD_DIR, "gen"); os.makedirs(gen_dir, exist_ok=True)
    base_apk = os.path.join(BUILD_DIR, "base.apk")
    run([bt_bin("aapt2"), "link", "-o", base_apk, "-I", ANDROID_JAR,
         "--manifest", os.path.join(SRC, "AndroidManifest.xml"), "--java", gen_dir,
         "--min-sdk-version", "24", "--target-sdk-version", "34",
         "--version-code", "1", "--version-name", VERSION,
         "--no-static-lib-packages"] + flata)

    print("[3/7] javac")
    classes = os.path.join(BUILD_DIR, "classes"); os.makedirs(classes, exist_ok=True)
    java_files = []
    for root, _dirs, files in os.walk(os.path.join(SRC, "java")):
        for f in files:
            if f.endswith(".java"): java_files.append(os.path.join(root, f))
    for root, _dirs, files in os.walk(gen_dir):
        for f in files:
            if f.endswith(".java"): java_files.append(os.path.join(root, f))
    with open(os.path.join(BUILD_DIR, "sources.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join('"' + p.replace("\\", "/").replace('"', r'\"') + '"' for p in java_files))
    run([jdk_bin("javac"), "--release", "8", "-encoding", "UTF-8", "-classpath", ANDROID_JAR,
         "-d", classes, "@" + os.path.join(BUILD_DIR, "sources.txt")])

    print("[4/7] d8")
    dex_dir = os.path.join(BUILD_DIR, "dex"); os.makedirs(dex_dir, exist_ok=True)
    class_files = []
    for root, _dirs, files in os.walk(classes):
        class_files += [os.path.join(root, f) for f in files if f.endswith(".class")]
    run([bt_bin("d8"), "--release", "--lib", ANDROID_JAR, "--output", dex_dir] + class_files)

    print("[5/7] inject classes.dex")
    with zipfile.ZipFile(base_apk, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(dex_dir, "classes.dex"), "classes.dex")

    print("[6/7] zipalign")
    aligned = os.path.join(BUILD_DIR, "aligned.apk")
    run([bt_bin("zipalign"), "-f", "4", base_apk, aligned])

    print("[7/7] sign")
    if not os.path.exists(KEYSTORE):
        run([jdk_bin("keytool"), "-genkeypair", "-keystore", KEYSTORE,
             "-storepass", KS_PASS, "-keypass", KS_PASS, "-alias", ALIAS,
             "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
             "-dname", "CN=KittenPuppy4Ever, OU=stjwls, O=stjwls, L=Shanghai, ST=Shanghai, C=CN"])
    run([bt_bin("apksigner"), "sign", "--ks", KEYSTORE, "--ks-pass", "pass:" + KS_PASS,
         "--key-pass", "pass:" + KS_PASS, "--out", OUT_APK, aligned])
    run([bt_bin("apksigner"), "verify", OUT_APK])
    print("\n构建完成：%s（%.1f KB）" % (OUT_APK, os.path.getsize(OUT_APK) / 1024))

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
