const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const ROOT = __dirname;
const PIPER = path.join(ROOT, ".venv/bin/piper");
const MODEL = path.join(ROOT, "voices/en_US-lessac-medium.onnx");
const AUDIO_DIR = path.join(ROOT, "audio");

const narration = JSON.parse(fs.readFileSync(path.join(ROOT, "narration.json"), "utf8"));

fs.mkdirSync(AUDIO_DIR, { recursive: true });

function wavDuration(file) {
  const out = execFileSync("ffprobe", [
    "-v", "error",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    file,
  ]).toString().trim();
  return parseFloat(out);
}

const manifest = [];

for (const scene of narration) {
  const wavPath = path.join(AUDIO_DIR, `${scene.id}.wav`);
  console.log(`Generating audio: ${scene.id}`);
  execFileSync(PIPER, [
    "-m", MODEL,
    "-f", wavPath,
    "--length-scale", "1.05",
    "--sentence-silence", "0.35",
  ], { input: scene.text });

  const duration = wavDuration(wavPath);
  manifest.push({ ...scene, wav: wavPath, duration });
  console.log(`  -> ${duration.toFixed(2)}s`);
}

fs.writeFileSync(
  path.join(ROOT, "audio-manifest.json"),
  JSON.stringify(manifest, null, 2)
);

console.log(`\nDone. ${manifest.length} audio clips written to ${AUDIO_DIR}`);
