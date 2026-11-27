import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright';

const out = process.env.OUT_DIR ?? '/out';
const maxAttempts = 4;
const result = { pass: false, attempts: [] };
mkdirSync(out, { recursive: true });

// This runs in each new document before the viewer creates its peer.
function observePeer() {
  window.RTCPeerConnection = class extends window.RTCPeerConnection {
    constructor(...args) {
      super(...args);
      const rtc = { connected: false, tracks: 0 };
      this.addEventListener('connectionstatechange', () => {
        rtc.connected = this.connectionState === 'connected';
      });
      this.addEventListener('track', ({ track }) => {
        if (track.kind === 'video') {
          rtc.tracks++;
          window.visualPeer = rtc;
        }
      });
    }
  };
}

function frames() {
  return document.getElementById('remote-video')?.getVideoPlaybackQuality().totalVideoFrames ?? 0;
}

function capture() {
  const video = document.getElementById('remote-video');
  if (!video?.videoWidth || !video.videoHeight) return null;
  const canvas = document.createElement('canvas');
  canvas.width = 320;
  canvas.height = Math.round(320 * video.videoHeight / video.videoWidth);
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(video, 0, 0, canvas.width, canvas.height);
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
  // Encode in chunks small enough for fromCharCode's argument limit.
  let bytes = '';
  for (let i = 0; i < pixels.length; i += 8192) {
    bytes += String.fromCharCode(...pixels.subarray(i, i + 8192));
  }
  return {
    rgba: btoa(bytes), image: canvas.toDataURL('image/png').split(',')[1],
    rtc: { connected: false, tracks: 0, ...window.visualPeer, video_width: video.videoWidth },
    height: video.videoHeight,
  };
}

let browser, context, page;
try {
  browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required',
    '--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
  context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  await context.tracing.start({ screenshots: true, snapshots: true });
  await context.addInitScript(observePeer);
  page = await context.newPage();
  for (let n = 1; n <= maxAttempts && !result.pass; n++) {
    const samples = [];
    let attemptError;
    try {
      await page.goto(process.env.BASE_URL, { waitUntil: 'domcontentloaded' });
      let previous = await page.evaluate(frames);
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline) {
        await page.waitForTimeout(1000);
        const current = await page.evaluate(frames);
        if (previous > 0 && current > previous) {
          const frame = await page.evaluate(capture);
          if (frame) {
            const verdict = JSON.parse(execFileSync('python3',
              ['/probe/verdict.py', JSON.stringify(frame.rtc)],
              { input: Buffer.from(frame.rgba, 'base64'), encoding: 'utf8' }));
            samples.push({ frames: current, ...frame.rtc, height: frame.height, ...verdict });
            writeFileSync(`${out}/video_frame.png`, Buffer.from(frame.image, 'base64'));
            result.pass = verdict.pass;
            if (result.pass || samples.length >= 6) break;
          }
        }
        previous = current;
      }
    } catch (error) {
      attemptError = String(error);
    }
    const attempt = { samples, error: attemptError };
    result.attempts.push(attempt);
    console.log(`Attempt ${n}: ${JSON.stringify(attempt)}`);
  }
} catch (error) {
  result.error = String(error);
} finally {
  writeFileSync(`${out}/result.json`, JSON.stringify(result, null, 2));
  try {
    await page?.screenshot({ path: `${out}/frame.png` });
  } finally {
    try {
      await context?.tracing.stop({ path: `${out}/trace.zip` });
    } finally {
      await browser?.close();
    }
  }
}
process.exitCode = result.pass ? 0 : 1;
