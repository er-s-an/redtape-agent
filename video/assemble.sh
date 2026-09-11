#!/bin/bash
# Assemble the RedTape demo video: cards (looped PNGs) + recorded footage + TTS voiceover.
# Usage: bash assemble.sh   (run after record.mjs; expects raw/*.webm)
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p seg raw out
VOICE="${REDTAPE_VOICE:-Samantha}"
RATE=190

say_seg() { # $1 name, $2 text file
  say -v "$VOICE" -r "$RATE" -o "seg/$1.aiff" --data-format=LEF32@22050 -f "$2"
  ffmpeg -y -loglevel error -i "seg/$1.aiff" -ar 44100 -ac 2 "seg/$1.wav"
}

card_png() { # $1 card id
  node -e "
import('playwright').then(async ({chromium}) => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport:{width:1440,height:900}});
  await p.goto('file://$PWD/cards.html?c=$1');
  await p.waitForTimeout(600);
  await p.screenshot({path:'seg/$1.png'});
  await b.close();
});"
}

dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }

make_card() { # $1 card id, $2 narration name
  card_png "$1"
  local d; d=$(dur "seg/$2.wav")
  ffmpeg -y -loglevel error -loop 1 -framerate 30 -i "seg/$1.png" -i "seg/$2.wav" \
    -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#faf7f2" \
    -t "$d" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "seg/$1.mp4"
}

# footage: speed up to roughly cover narration, then attach narration (or keep silent tail)
make_footage() { # $1 webm file, $2 narration name, $3 speed factor
  local d; d=$(dur "seg/$2.wav")
  ffmpeg -y -loglevel error -i "$1" -i "seg/$2.wav" \
    -filter_complex "[0:v]setpts=PTS/$3,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#faf7f2[v]" \
    -map "[v]" -map 1:a -t "$d" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "seg/$2.mp4"
}

echo "1/ narration"; for s in s1 s2 s4 s6 s8 s9 s3 s5 s7; do say_seg "$s" "narration/$s.txt"; done
echo "2/ cards"; make_card title s1; make_card problem s2; make_card plan s4; make_card decision s6; make_card trust s8; make_card close s9
echo "3/ footage"
make_footage "$(ls raw/*.webm | head -1)" s3 8 &
wait
echo "4/ concat"
cat > seg/list.txt <<EOF
file 'title.mp4'
file 'problem.mp4'
file 's3.mp4'
file 'plan.mp4'
file 'decision.mp4'
file 'trust.mp4'
file 'close.mp4'
EOF
ffmpeg -y -loglevel error -f concat -safe 0 -i seg/list.txt -c copy out/redtape-demo.mp4
echo "done → video/out/redtape-demo.mp4"; dur out/redtape-demo.mp4
