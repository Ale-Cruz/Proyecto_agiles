"""Compilación local sin cambiar scripts del SDK ni opciones globales."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
FLUTTER = Path(os.getenv('FLUTTER_ROOT', r'C:\dev\flutter'))
LOCAL_USER = Path(r'C:\Users\aleja')
env = dict(os.environ)
env.update(
    FLUTTER_WINDOWS='false', FLUTTER_ROOT=str(FLUTTER),
    PUB_CACHE=str(ROOT / '.pub-cache'),
    GRADLE_USER_HOME=str(LOCAL_USER / '.gradle'),
    ANDROID_USER_HOME=str(FLUTTER / 'bin/cache/cafeteria-android'),
    JAVA_HOME=r'C:\Program Files\Android\Android Studio\jbr',
    JAVA_TOOL_OPTIONS='-Duser.home=C:/Users/aleja',
    JAVA_OPTS='-Duser.home=C:/Users/aleja',
    GRADLE_OPTS='-Dorg.gradle.configuration-cache=false -Dorg.gradle.daemon=false',
)
android_home = Path(env['ANDROID_USER_HOME'])
android_home.mkdir(exist_ok=True)
existing_key = LOCAL_USER / '.android/debug.keystore'
local_key = android_home / 'debug.keystore'
if existing_key.exists() and not local_key.exists():
    shutil.copy2(existing_key, local_key)
env.pop('DEBUG', None)
sys.stdout.reconfigure(encoding='utf-8')
dart = str(FLUTTER / 'bin/cache/dart-sdk/bin/dart.exe')
snapshot = str(FLUTTER / 'bin/cache/flutter_tools.snapshot')
mode = sys.argv[1] if len(sys.argv) > 1 else 'apk'
if mode == 'test':
    command = [dart, snapshot, '--suppress-analytics', 'test', '--no-pub']
elif mode == 'analyze':
    command = [dart, '--suppress-analytics', 'analyze', 'lib', 'test']
elif mode == 'format':
    command = [dart, '--suppress-analytics', 'format', 'lib', 'test']
else:
    local = ROOT / '.build-tools'
    local.mkdir(exist_ok=True)
    wrapper = local / 'flutter_local.cmd'
    wrapper.write_text('@echo off\n"' + dart + '" "' + snapshot + '" --suppress-analytics %*\n', encoding='utf-8')
    # Copias de los jars autorizados del SDK; javac necesita resolver todas
    # las carpetas de AppData y esa consulta está restringida en esta sesión.
    sdk = Path(r'C:/Users/aleja/AppData/Local/Android/Sdk')
    ndk_version = '28.2.13676358'
    ndk_source = sdk / 'ndk' / ndk_version
    ndk_cache = FLUTTER / 'bin/cache/cafeteria-ndk' / ndk_version
    marker = ndk_cache / '.cafeteria-ready'
    if not marker.exists():
        print('Preparando caché del NDK instalado (enlaces, sin duplicar sus datos).', flush=True)
        ndk_cache.mkdir(parents=True, exist_ok=True)
        for source in ndk_source.rglob('*'):
            target = ndk_cache / source.relative_to(ndk_source)
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.link(source, target)
        marker.write_text(ndk_version, encoding='ascii')
    env['CAFE_LOCAL_NDK'] = str(ndk_cache)

    compile_cache = FLUTTER / 'bin/cache/cafeteria-javac'
    compile_cache.mkdir(exist_ok=True)
    jar_dir = compile_cache / 'sdk-jars'
    jar_dir.mkdir(exist_ok=True)
    jar_map = {}
    for folder in [sdk / 'platforms/android-36', sdk / 'build-tools/36.0.0']:
        for jar in folder.glob('*.jar'):
            target = jar_dir / (folder.name + '-' + jar.name)
            if not target.exists() or target.stat().st_mtime != jar.stat().st_mtime:
                shutil.copy2(jar, target)
            jar_map[jar.as_posix().lower()] = str(target)
    mapping = local / 'sdk-jars.json'
    mapping.write_text(json.dumps(jar_map), encoding='utf-8')
    env['CAFE_SDK_JARS'] = str(mapping)
    env['CAFE_JAVA_JAR_CACHE'] = str(compile_cache / 'jars')
    init = local / 'flutter_local.init.gradle'
    init.write_text("""import groovy.json.JsonSlurper
def sdkJars = new JsonSlurper().parse(new File(System.getenv('CAFE_SDK_JARS')))
def copiedJars = new File(System.getenv('CAFE_JAVA_JAR_CACHE'))
copiedJars.mkdirs()
def localJar = { f ->
    def key = f.absolutePath.replace((char)92, (char)47).toLowerCase()
    if (!f.isFile() || !f.name.endsWith('.jar')) return f
    if (sdkJars[key]) return new File(sdkJars[key])
    def id = java.security.MessageDigest.getInstance('SHA-256').digest(key.bytes).encodeHex().toString()
    def target = new File(copiedJars, id + '.jar')
    synchronized(copiedJars) {
        if (!target.exists() || target.length() != f.length() || target.lastModified() != f.lastModified()) {
            java.nio.file.Files.copy(f.toPath(), target.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
            target.setLastModified(f.lastModified())
        }
    }
    target
}
gradle.beforeProject { p ->
    ['com.android.application', 'com.android.library'].each { pluginId ->
        p.plugins.withId(pluginId) {
            p.extensions.getByName('androidComponents').finalizeDsl { dsl ->
                dsl.ndkPath = System.getenv('CAFE_LOCAL_NDK')
                dsl.ndkVersion = '28.2.13676358'
            }
        }
    }
}
gradle.projectsEvaluated {
    gradle.rootProject.allprojects { p ->
        p.tasks.withType(org.gradle.api.tasks.compile.JavaCompile).configureEach { task ->
            task.doFirst {
                task.classpath = p.files(task.classpath.files.collect(localJar))
                if (task.options.bootstrapClasspath != null) {
                    task.options.bootstrapClasspath = p.files(task.options.bootstrapClasspath.files.collect(localJar))
                }
            }
        }
        p.tasks.matching { it.name.startsWith('compileFlutterBuild') }.configureEach {
            flutterExecutable = new File(System.getenv('CAFE_FLUTTER_EXECUTABLE'))
        }
    }
}
""", encoding='utf-8')
    env['CAFE_FLUTTER_EXECUTABLE'] = str(wrapper)
    address = os.getenv('API_BASE_URL', 'http://192.168.0.5:8001/api/v1')
    define = base64.b64encode(('API_BASE_URL=' + address).encode()).decode()
    command = [str(ROOT / 'android/gradlew.bat'), '--no-daemon', '--no-configuration-cache',
               '--init-script', str(init), '--stacktrace',
               '-Ptarget-platform=android-arm,android-arm64,android-x64',
               '-Ptarget=lib/main.dart', '-Pdart-defines=' + define, 'assembleDebug']
log_dir = ROOT / '.build-logs'
log_dir.mkdir(exist_ok=True)
log_path = log_dir / (mode + '.txt')
print('Ejecutando', mode, '. Registro:', log_path, flush=True)
with log_path.open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=ROOT / 'android' if mode == 'apk' else ROOT,
                            env=env, stdout=log, stderr=subprocess.STDOUT)
print('\n'.join(log_path.read_text(encoding='utf-8', errors='replace').splitlines()[-65:]), flush=True)
raise SystemExit(result.returncode)
