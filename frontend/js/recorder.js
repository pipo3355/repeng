// Microphone capture -> 16 kHz mono 16-bit WAV, with optional silence auto-stop.
// Optionally runs the browser's speech recognition in parallel (STT provider "browser").

const WORKLET = `
class Cap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor('cap', Cap);
`;

const TARGET_RATE = 16000;

export class Recorder {
  constructor() {
    this.ctx = null;
    this.chunks = [];
    this.recording = false;
    this.onLevel = null;
    this.onAutoStop = null;
  }

  async start({ autoStop = true, browserSTT = false } = {}) {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    this.ctx = new AudioContext();
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
    await this.ctx.audioWorklet.addModule(url);
    URL.revokeObjectURL(url);
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, 'cap');
    this.chunks = [];
    this.recording = true;
    this.speechStarted = false;
    this.lastVoice = performance.now();
    this.startedAt = performance.now();
    // adaptive noise floor
    this.noise = 0.01;

    this.node.port.onmessage = (e) => {
      if (!this.recording) return;
      const buf = e.data;
      this.chunks.push(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      if (this.onLevel) this.onLevel(rms);
      const t = performance.now();
      if (t - this.startedAt < 400) { this.noise = Math.max(this.noise * 0.9 + rms * 0.1, 0.004); return; }
      const threshold = Math.max(this.noise * 3, 0.015);
      if (rms > threshold) { this.speechStarted = true; this.lastVoice = t; }
      else if (!this.speechStarted) this.noise = this.noise * 0.95 + rms * 0.05;
      if (autoStop && this.speechStarted && t - this.lastVoice > 1600 && this.onAutoStop) {
        const cb = this.onAutoStop; this.onAutoStop = null; cb();
      }
      if (t - this.startedAt > 90000 && this.onAutoStop) { const cb = this.onAutoStop; this.onAutoStop = null; cb(); }
    };
    this.source.connect(this.node);

    this.transcript = '';
    this.recognition = null;
    if (browserSTT) {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (SR) {
        const rec = new SR();
        rec.lang = 'en-US';
        rec.continuous = true;
        rec.interimResults = false;
        rec.onresult = (e) => {
          for (let i = e.resultIndex; i < e.results.length; i++) {
            if (e.results[i].isFinal) this.transcript += e.results[i][0].transcript + ' ';
          }
        };
        this.recEnded = new Promise((res) => { rec.onend = res; rec.onerror = res; });
        try { rec.start(); this.recognition = rec; } catch { this.recognition = null; }
      }
    }
  }

  async stop() {
    if (!this.recording) return null;
    this.recording = false;
    this.source.disconnect();
    this.node.disconnect();
    this.stream.getTracks().forEach((t) => t.stop());
    const rate = this.ctx.sampleRate;
    await this.ctx.close();
    if (this.recognition) {
      try { this.recognition.stop(); } catch {}
      await Promise.race([this.recEnded, new Promise((r) => setTimeout(r, 2500))]);
    }
    const len = this.chunks.reduce((a, c) => a + c.length, 0);
    const all = new Float32Array(len);
    let off = 0;
    for (const c of this.chunks) { all.set(c, off); off += c.length; }
    const pcm = resample(trimSilence(all, rate), rate, TARGET_RATE);
    return {
      wav: encodeWav(pcm, TARGET_RATE),
      duration: pcm.length / TARGET_RATE,
      text: this.transcript.trim(),
      hadSpeech: this.speechStarted,
    };
  }
}

function trimSilence(a, rate) {
  const win = Math.floor(rate * 0.02);
  const thr = 0.01;
  let s = 0, e = a.length;
  const energy = (i) => { let m = 0; for (let j = i; j < Math.min(i + win, a.length); j++) m = Math.max(m, Math.abs(a[j])); return m; };
  while (s < a.length && energy(s) < thr) s += win;
  while (e > s && energy(Math.max(e - win, 0)) < thr) e -= win;
  const pad = Math.floor(rate * 0.25);
  return a.subarray(Math.max(0, s - pad), Math.min(a.length, e + pad));
}

function resample(a, from, to) {
  if (from === to) return a;
  const ratio = from / to;
  const n = Math.floor(a.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    // average over the source window (cheap low-pass) to avoid aliasing
    const start = Math.floor(i * ratio), end = Math.min(a.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += a[j];
    out[i] = end > start ? sum / (end - start) : a[start] || 0;
  }
  return out;
}

function encodeWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}
