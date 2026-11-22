[app]
title = PHL Calculator
package.name = phlcalculator
package.domain = org.civmatics

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
source.exclude_dirs = .github,bin,.buildozer

version = 1.0.0

requirements = python3,kivy==2.3.0

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/data/icon.png
presplash.filename = %(source.dir)s/data/presplash.png
android.presplash_color = #fde4df

# No special permissions needed (data is stored in the app's private folder)
android.permissions =

android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
