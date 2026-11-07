# Adds the release files the app downloads (newest APK, speech model) to a copy of the public
# update repository, at the paths the app's China addresses use: releases/<tag>/<file>.
import json, os, subprocess, sys
src = sys.argv[1]
REL = 'https://github.com/infcreative-Ethan/evolve-english-updates/releases/download/'
want = [json.load(open(f'{src}/latest.json'))['apkUrl'], REL + 'model-w2v-1/d2v-int8.onnx']
for url in want:
    assert url.startswith(REL), url
    out = os.path.join(src, 'releases', url[len(REL):])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(['curl', '-sSfL', '--retry', '3', '-o', out, url], check=True)
    print(out, os.path.getsize(out) // 1048576, 'MB')
