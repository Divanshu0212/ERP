/**
 * Muxes each scene's recorded video (video-raw/<id>.webm) with its generated
 * narration audio (audio/<id>.wav), padding the video with its last frame if the
 * audio runs longer, then concatenates every scene into one final MP4.
 *
 * Usage: node 03-assemble.js
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = __dirname;
const VIDEO_DIR = path.join(ROOT, "video-raw");
const AUDIO_DIR = path.join(ROOT, "audio");
const SCENES_DIR = path.join(ROOT, "scenes");
const FINAL_DIR = path.join(ROOT, "final");

fs.mkdirSync(SCENES_DIR, { recursive: true });
fs.mkdirSync(FINAL_DIR, { recursive: true });

const narration = JSON.parse(fs.readFileSync(path.join(ROOT, "narration.json"), "utf8"));

function ffprobeDuration(file) {
  const out = execFileSync("ffprobe", [
    "-v", "error",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    file,
  ]).toString().trim();
  return parseFloat(out);
}

function run(args) {
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", ...args], { stdio: "inherit" });
}

function srtTimestamp(seconds) {
  const ms = Math.round(seconds * 1000);
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const msec = ms % 1000;
  const pad = (n, w) => String(n).padStart(w, "0");
  return `${pad(h, 2)}:${pad(m, 2)}:${pad(s, 2)},${pad(msec, 3)}`;
}

// Splits narration text into short subtitle-sized chunks (~10 words) and
// distributes them proportionally (by word count) across the scene's actual
// on-timeline duration, so cues roughly track the speech even though we don't
// have word-level timing from Piper.
function chunkForSubtitles(text, maxWords = 10) {
  const words = text.split(/\s+/).filter(Boolean);
  const chunks = [];
  for (let i = 0; i < words.length; i += maxWords) {
    chunks.push(words.slice(i, i + maxWords).join(" "));
  }
  return chunks;
}

const srtCues = [];
let timelineOffset = 0; // seconds

const sceneFiles = [];

for (const scene of narration) {
  const videoIn = path.join(VIDEO_DIR, `${scene.id}.webm`);
  const audioIn = path.join(AUDIO_DIR, `${scene.id}.wav`);
  const out = path.join(SCENES_DIR, `${scene.id}.mp4`);

  if (!fs.existsSync(videoIn)) {
    console.log(`SKIP ${scene.id}: no recorded video at ${videoIn}`);
    continue;
  }
  if (!fs.existsSync(audioIn)) {
    console.log(`SKIP ${scene.id}: no audio at ${audioIn}`);
    continue;
  }

  const videoDur = ffprobeDuration(videoIn);
  const audioDur = ffprobeDuration(audioIn);
  console.log(`${scene.id}: video=${videoDur.toFixed(2)}s audio=${audioDur.toFixed(2)}s`);

  if (videoDur >= audioDur) {
    // video already covers the narration — just mux, trim video to audio length + 0.3s tail
    run([
      "-i", videoIn,
      "-i", audioIn,
      "-t", (audioDur + 0.3).toFixed(2),
      "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
      "-c:a", "aac", "-b:a", "160k",
      "-shortest",
      out,
    ]);
  } else {
    // pad video by freezing its last frame until the audio finishes
    const padSeconds = (audioDur - videoDur + 0.3).toFixed(2);
    run([
      "-i", videoIn,
      "-i", audioIn,
      "-filter_complex",
      `[0:v]tpad=stop_mode=clone:stop_duration=${padSeconds}[v]`,
      "-map", "[v]", "-map", "1:a",
      "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
      "-c:a", "aac", "-b:a", "160k",
      out,
    ]);
  }

  sceneFiles.push(out);

  const sceneFinalDuration = ffprobeDuration(out);
  const chunks = chunkForSubtitles(scene.text);
  const perChunk = sceneFinalDuration / chunks.length;
  chunks.forEach((chunk, i) => {
    const start = timelineOffset + i * perChunk;
    const end = timelineOffset + (i + 1) * perChunk;
    srtCues.push({ start, end, text: chunk });
  });
  timelineOffset += sceneFinalDuration;
}

if (sceneFiles.length === 0) {
  console.error("No scenes assembled — nothing to concatenate.");
  process.exit(1);
}

const listPath = path.join(SCENES_DIR, "concat-list.txt");
fs.writeFileSync(listPath, sceneFiles.map((f) => `file '${f}'`).join("\n"));

const srtPath = path.join(FINAL_DIR, "su-erp-demo.srt");
const srtBody = srtCues
  .map((cue, i) => `${i + 1}\n${srtTimestamp(cue.start)} --> ${srtTimestamp(cue.end)}\n${cue.text}\n`)
  .join("\n");
fs.writeFileSync(srtPath, srtBody);
console.log(`\nSubtitles: ${srtPath} (${srtCues.length} cues)`);

const concatOut = path.join(SCENES_DIR, "concat-no-subs.mp4");
run([
  "-f", "concat", "-safe", "0",
  "-i", listPath,
  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
  "-c:a", "aac", "-b:a", "160k",
  concatOut,
]);

const finalOut = path.join(FINAL_DIR, "su-erp-demo.mp4");
// Burn subtitles in (bottom third, above the existing scene-caption bar) so
// the video is watchable with sound off. escape special chars ffmpeg's
// filtergraph parser is picky about (colons, backslashes) in the path.
const escapedSrtPath = srtPath.replace(/\\/g, "\\\\").replace(/:/g, "\\:");
const subtitleStyle =
  "FontName=DejaVu Sans,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1.4,Shadow=0,MarginV=90,Alignment=2";
run([
  "-i", concatOut,
  "-vf", `subtitles=${escapedSrtPath}:force_style='${subtitleStyle}'`,
  "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
  "-c:a", "copy",
  finalOut,
]);

console.log(`\nFinal video: ${finalOut}`);
console.log(`Duration: ${ffprobeDuration(finalOut).toFixed(1)}s`);
