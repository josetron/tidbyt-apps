"""
Builds the Tidbyt Mirror Android TV app without Gradle, using only the Android SDK tools.

  python android_tv/build.py              -> android_tv/build/tidbyt-mirror.apk
  python android_tv/build.py --install    also installs it on the device adb sees (or pass
                                          --device 192.168.68.88:5555) and starts it
  python android_tv/build.py --copy-to "Z:\\My Apps\\Tidbyt"
                                          also saves it there as TidbytMirror-<version>-androidtv.apk
  --debuggable                            lets "adb shell run-as" read the app's saved settings

The version is VERSION in tools/tidbyt_mirror.py, shared with the Windows .exe.

Needs: the Android SDK (build-tools + a platform; ANDROID_HOME, or E:\\Android\\Sdk, or the default
%LOCALAPPDATA%\\Android\\Sdk) and a JDK (JAVA_HOME, or Android Studio's bundled one).
The APK is signed with the standard debug key (%USERPROFILE%\\.android\\debug.keystore, created
on first use), which is fine for installing on your own TV.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
PACKAGE = "com.josetron.tidbytmirror"
with open(os.path.join(os.path.dirname(HERE), "tools", "tidbyt_mirror.py"), encoding="utf-8") as _f:
    VERSION = re.search(r'^VERSION = "([^"]+)"', _f.read(), re.M).group(1)
VERSION_CODE = sum(int(n) * m for n, m in zip(VERSION.split("."), (10000, 100, 1)))  # 1.2.3 -> 10203
EXE = ".exe" if os.name == "nt" else ""


def first(paths, what):
    for p in paths:
        if p and os.path.exists(p):
            return p
    sys.exit("Could not find %s. Looked in: %s" % (what, ", ".join(p for p in paths if p)))


def newest(pattern, what):
    found = sorted(glob.glob(pattern))
    if not found:
        sys.exit("Could not find %s (%s)" % (what, pattern))
    return found[-1]


def run(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("FAILED: %s\n%s%s" % (" ".join(args[:3]), r.stdout, r.stderr))
    return r.stdout


def main():
    sdk = first([os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), r"E:\Android\Sdk",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")], "the Android SDK")
    java_home = first([os.environ.get("JAVA_HOME"), r"E:\Android\Android Studio\jbr",
                       r"C:\Program Files\Android\Android Studio\jbr"], "a JDK")
    java, javac = [os.path.join(java_home, "bin", n + EXE) for n in ("java", "javac")]
    keytool = os.path.join(java_home, "bin", "keytool" + EXE)
    tools = newest(os.path.join(sdk, "build-tools", "*"), "Android build-tools")
    android_jar = os.path.join(newest(os.path.join(sdk, "platforms", "android-*"), "an Android platform"), "android.jar")
    aapt2, zipalign = [os.path.join(tools, n + EXE) for n in ("aapt2", "zipalign")]
    d8_jar, signer_jar = [os.path.join(tools, "lib", n) for n in ("d8.jar", "apksigner.jar")]

    shutil.rmtree(BUILD, ignore_errors=True)
    for d in ("gen", "classes", "dex"):
        os.makedirs(os.path.join(BUILD, d))

    # resources + manifest -> APK skeleton and R.java
    res_zip = os.path.join(BUILD, "res.zip")
    run(aapt2, "compile", "--dir", os.path.join(HERE, "res"), "-o", res_zip)
    unsigned = os.path.join(BUILD, "unsigned.apk")
    run(aapt2, "link", "-o", unsigned, "-I", android_jar, "--manifest", os.path.join(HERE, "AndroidManifest.xml"),
        "--java", os.path.join(BUILD, "gen"), "--min-sdk-version", "23", "--target-sdk-version", "34",
        "--version-code", str(VERSION_CODE), "--version-name", VERSION,
        *(["--debug-mode"] if "--debuggable" in sys.argv else []), res_zip)

    # Java -> classes -> dex
    sources = glob.glob(os.path.join(HERE, "src", "**", "*.java"), recursive=True) + \
        glob.glob(os.path.join(BUILD, "gen", "**", "*.java"), recursive=True)
    run(javac, "-nowarn", "-Xlint:-options", "-source", "8", "-target", "8", "-bootclasspath", android_jar,
        "-d", os.path.join(BUILD, "classes"), *sources)
    classes = glob.glob(os.path.join(BUILD, "classes", "**", "*.class"), recursive=True)
    run(java, "-cp", d8_jar, "com.android.tools.r8.D8", "--lib", android_jar, "--min-api", "23",
        "--output", os.path.join(BUILD, "dex"), *classes)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(BUILD, "dex", "classes.dex"), "classes.dex")

    # align + sign
    aligned = os.path.join(BUILD, "aligned.apk")
    run(zipalign, "-f", "4", unsigned, aligned)
    keystore = os.path.join(os.path.expanduser("~"), ".android", "debug.keystore")
    if not os.path.exists(keystore):
        os.makedirs(os.path.dirname(keystore), exist_ok=True)
        run(keytool, "-genkeypair", "-keystore", keystore, "-storepass", "android", "-keypass", "android",
            "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-dname", "CN=Android Debug,O=Android,C=US")
    apk = os.path.join(BUILD, "tidbyt-mirror.apk")
    run(java, "-jar", signer_jar, "sign", "--ks", keystore, "--ks-pass", "pass:android", "--key-pass", "pass:android",
        "--ks-key-alias", "androiddebugkey", "--out", apk, aligned)
    print("built %s, version %s (%d KB)" % (apk, VERSION, os.path.getsize(apk) // 1024))
    if "--copy-to" in sys.argv:
        dest = os.path.join(sys.argv[sys.argv.index("--copy-to") + 1], "TidbytMirror-%s-androidtv.apk" % VERSION)
        shutil.copyfile(apk, dest)
        print("saved %s" % dest)

    if "--install" in sys.argv:
        adb = [os.path.join(sdk, "platform-tools", "adb" + EXE)]
        if "--device" in sys.argv:
            adb += ["-s", sys.argv[sys.argv.index("--device") + 1]]
        print(run(*adb, "install", "-r", apk).strip())
        # lets the app's setup menu switch the TV's screen saver to itself (and back)
        run(*adb, "shell", "pm", "grant", PACKAGE, "android.permission.WRITE_SECURE_SETTINGS")
        run(*adb, "shell", "am", "start", "-n", PACKAGE + "/.MainActivity")
        print("started on the device")


if __name__ == "__main__":
    main()
