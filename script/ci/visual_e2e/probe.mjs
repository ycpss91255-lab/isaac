import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright';

const MAX_RECORDED_ATTEMPTS = 20;
const RETRY_BACKOFF_MS = 1000;
const out = process.env.OUT_DIR ?? '/out';
const budgetMs = Number(process.env.VISUAL_E2E_TOTAL_TIMEOUT_S ?? 600) * 1000;
const start = Date.now();
const deadline = start + budgetMs;
const result = { pass: false, attemptCount: 0, attempts: [] };
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
let lastFrameVerdict = 'no frame';
try {
  browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required',
    '--use-gl=swiftshader', '--enable-unsafe-swiftshader'] });
  context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  await context.tracing.start({ screenshots: true, snapshots: true });
  await context.addInitScript(observePeer);
  page = await context.newPage();
  while (Date.now() < deadline && !result.pass) {
    result.attemptCount++;
    const samples = [];
    let attemptError;
    try {
      await page.goto(process.env.BASE_URL, { waitUntil: 'domcontentloaded',
        timeout: Math.max(1, Math.min(30000, deadline - Date.now())) });
      let previous = await page.evaluate(frames);
      const attemptDeadline = Math.min(Date.now() + 30000, deadline);
      while (Date.now() < attemptDeadline) {
        await page.waitForTimeout(Math.min(1000, attemptDeadline - Date.now()));
        const current = await page.evaluate(frames);
        if (previous > 0 && current > previous) {
          const frame = await page.evaluate(capture);
          if (frame) {
            const verdict = JSON.parse(execFileSync('python3',
              ['/probe/verdict.py', JSON.stringify(frame.rtc)],
              { input: Buffer.from(frame.rgba, 'base64'), encoding: 'utf8' }));
            samples.push({ frames: current, ...frame.rtc, height: frame.height, ...verdict });
            lastFrameVerdict = verdict;
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
    if (result.attempts.length < MAX_RECORDED_ATTEMPTS) {
      result.attempts.push(attempt);
      console.log(`Attempt ${result.attemptCount}: ${JSON.stringify(attempt)}`);
    }
    if (!result.pass && Date.now() < deadline) {
      await page.waitForTimeout(Math.min(RETRY_BACKOFF_MS, deadline - Date.now()));
    }
  }
} catch (error) {
  result.error = String(error);
} finally {
  if (!result.pass) {
    result.totalWaitSeconds = (Date.now() - start) / 1000;
    result.lastFrameVerdict = lastFrameVerdict;
    console.log(`Waited ${result.totalWaitSeconds}s. Last frame verdict: ${JSON.stringify(lastFrameVerdict)}`);
  }
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
