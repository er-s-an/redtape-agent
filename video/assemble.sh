#!/bin/bash
# Assemble the RedTape demo video: cards + three recorded segments + TTS voiceover.
# Run after record.mjs (expects raw/{wake,decision,execution}.webm).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p seg out
VOICE="${REDTAPE_VOICE:-Samantha}"
RATE=195

say_seg() { say -v "$VOICE" -r "$RATE" -o "seg/$1.aiff" --data-format=LEF32@22050 -f "narration/$1.txt"
            ffmpeg -y -loglevel error -i "seg/$1.aiff" -ar 44100 -ac 2 "seg/$1.wav"; }
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }

card_png() { node -e "
import('playwright').then(async ({chromium}) => {
  const b = await chromium.launch();
  const p = await b.newPage({viewport:{width:1440,height:900}});
  await p.goto('file://$PWD/cards.html?c=$1');
  await p.waitForTimeout(600);
  await p.screenshot({path:'seg/$1.png'});
  await b.close();
});"; }

SCALE="scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"

make_card() { # $1 card id, $2 narration id
  card_png "$1"
  local d; d=$(dur "seg/$2.wav")
  ffmpeg -y -loglevel error -loop 1 -framerate 30 -i "seg/$1.png" -i "seg/$2.wav" \
    -vf "$SCALE" -t "$d" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "seg/$2.mp4"
}

make_footage() { # $1 out id, $2 webm, $3 start sec, $4 speed, $5 narration id
  local d; d=$(dur "seg/$5.wav")
  ffmpeg -y -loglevel error -ss "$3" -i "$2" -i "seg/$5.wav" \
    -filter_complex "[0:v]setpts=PTS/$4,$SCALE[v]" \
    -map "[v]" -map 1:a -t "$d" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "seg/$1.mp4"
}

echo "1/4 narration"; for s in s1 s2 s3 s4 s5 s6 s7 s8 s9; do say_seg "$s"; done
echo "2/4 cards"; make_card title s1 & make_card problem s2 & make_card plan s4 & wait
make_card decision s6 & make_card trust s8 & make_card close s9 & wait
echo "3/4 footage"
WAKE_LEN=$(dur raw/wake.webm)
HALF=$(awk "BEGIN{printf \"%.1f\", $WAKE_LEN * 0.45}")
make_footage s3 raw/wake.webm 0 8 s3
make_footage s5 raw/wake.webm "$HALF" 6 s5
D7=$(dur "seg/s7.wav")
ffmpeg -y -loglevel error -i raw/decision.webm -filter_complex "[0:v]setpts=PTS/1,$SCALE[v]" -an -c:v libx264 -pix_fmt yuv420p "seg/s7a_v.mp4"
ffmpeg -y -loglevel error -i raw/execution.webm -filter_complex "[0:v]setpts=PTS/5,$SCALE[v]" -an -c:v libx264 -pix_fmt yuv420p "seg/s7b_v.mp4"
ffmpeg -y -loglevel error -i "seg/s7a_v.mp4" -i "seg/s7b_v.mp4" \
  -filter_complex "[0:v][1:v]concat=n=2:v=1[v]" -map "[v]" -c:v libx264 -pix_fmt yuv420p "seg/s7_v.mp4"
ffmpeg -y -loglevel error -i "seg/s7_v.mp4" -i "seg/s7.wav" -map 0:v -map 1:a -t "$D7" \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "seg/s7.mp4"
echo "4/4 concat"
cat > seg/list.txt <<'EOF'
file 's1.mp4'
file 's2.mp4'
file 's3.mp4'
file 's4.mp4'
file 's5.mp4'
file 's6.mp4'
file 's7.mp4'
file 's8.mp4'
file 's9.mp4'
EOF
ffmpeg -y -loglevel error -f concat -safe 0 -i seg/list.txt -c:v libx264 -pix_fmt yuv420p -c:a aac out/redtape-demo.mp4
echo "done → video/out/redtape-demo.mp4"; dur out/redtape-demo.mp4
