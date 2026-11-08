// Text-to-speech: browser speechSynthesis or server (/api/tts) depending on settings.
import { api, state, toast } from './api.js';

let currentAudio = null;
let currentUtterance = null; // keep a reference: Chrome can garbage-collect a playing utterance and go silent
let voicesReady = null;

function loadVoices() {
  if (!('speechSynthesis' in window)) return Promise.resolve([]);
  if (voicesReady) return voicesReady;
  voicesReady = new Promise((resolve) => {
    const got = speechSynthesis.getVoices();
    if (got.length) return resolve(got);
    const done = () => resolve(speechSynthesis.getVoices());
    speechSynthesis.addEventListener('voiceschanged', done, { once: true });
    setTimeout(done, 1500); // some browsers never fire voiceschanged
  });
  return voicesReady;
}
loadVoices();

export async function englishVoices() {
  return (await loadVoices()).filter((v) => v.lang && v.lang.toLowerCase().startsWith('en'));
}

async function pickVoice() {
  const voices = await englishVoices();
  const accent = (state.settings?.tutor?.accent || 'en-US').toLowerCase();
  const pref = (v) => (v.lang.toLowerCase().replace('_', '-') === accent ? 2 : 0) + (/natural|neural|online|google/i.test(v.name) ? 1 : 0);
  return voices.sort((a, b) => pref(b) - pref(a))[0] || null;
}

async function pickRussianVoice() {
  const voices = (await loadVoices()).filter((v) => v.lang && v.lang.toLowerCase().startsWith('ru'));
  const pref = (v) => (/natural|neural|online|google/i.test(v.name) ? 1 : 0);
  return voices.sort((a, b) => pref(b) - pref(a))[0] || null;
}

const CYR = /[А-Яа-яЁё]/;

/** Split text into runs of Russian and non-Russian text: [{ru: bool, text}]. */
export function splitByLanguage(text) {
  const parts = [];
  // a Russian run starts at a Cyrillic letter and continues through Cyrillic letters, digits, spaces and punctuation
  const re = /[А-Яа-яЁё][А-Яа-яЁё0-9\s.,!?;:«»"'()\-–—…]*/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push({ ru: false, text: text.slice(last, m.index) });
    parts.push({ ru: true, text: m[0] });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ ru: false, text: text.slice(last) });
  return parts.map((p) => ({ ...p, text: p.text.trim() })).filter((p) => /[\p{L}\p{N}]/u.test(p.text));
}

export function stopSpeaking() {
  speakBrowser.token = null;
  if ('speechSynthesis' in window && (speechSynthesis.speaking || speechSynthesis.pending)) speechSynthesis.cancel();
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function speakBrowser(text, rate) {
  if (!('speechSynthesis' in window)) {
    toast('Этот браузер не умеет озвучивать текст. Откройте приложение в Chrome или Edge либо выберите Azure-озвучку в настройках.', true, 8000);
    return;
  }
  const wasBusy = speechSynthesis.speaking || speechSynthesis.pending;
  if (wasBusy) {
    speechSynthesis.cancel();
    await wait(80); // Chrome drops an utterance queued right after cancel()
  }
  const voice = await pickVoice();
  if (!voice) toast('В системе не найден английский голос — будет использован голос по умолчанию. Можно установить English (US) в Windows: Параметры → Время и язык → Речь.', false, 8000);
  let parts = splitByLanguage(text);
  const ruVoice = parts.some((p) => p.ru) ? await pickRussianVoice() : null;
  // Without a Russian voice, skip Russian fragments rather than mangle them with an English voice.
  if (!ruVoice) parts = parts.filter((p) => !p.ru);
  const token = {};
  speakBrowser.token = token;
  for (const part of parts) {
    if (speakBrowser.token !== token) break; // a newer speak() or stop interrupted us
    const v = part.ru ? ruVoice : voice;
    const u = new SpeechSynthesisUtterance(part.text);
    if (v) u.voice = v;
    u.lang = v?.lang || (part.ru ? 'ru-RU' : 'en-US');
    u.rate = part.ru ? Math.max(rate, 1) : rate;
    u.volume = 1;
    currentUtterance = u;
    const ok = await new Promise((resolve) => {
      u.onend = () => resolve(true);
      u.onerror = (e) => {
        if (e.error !== 'interrupted' && e.error !== 'canceled') {
          toast(`Озвучка не сработала (${e.error}). ${e.error === 'not-allowed' ? 'Браузер заблокировал звук: кликните по странице и повторите.' : ''}`, true, 8000);
        }
        resolve(false);
      };
      speechSynthesis.speak(u);
      if (speechSynthesis.paused) speechSynthesis.resume(); // Chrome can get stuck in the paused state
    });
    if (currentUtterance === u) currentUtterance = null;
    if (!ok) break;
  }
}

export async function speak(text, { rate } = {}) {
  if (!text) return;
  if (state.settings?.tutor?.voice_english_only) {
    text = splitByLanguage(text).filter((p) => !p.ru).map((p) => p.text).join(' ');
    if (!text) return;
  }
  const tts = state.settings?.tts || { provider: 'browser', rate: 1 };
  rate = rate ?? Number(tts.rate || 1);
  if (tts.provider === 'browser') return speakBrowser(text, rate);
  stopSpeaking();
  try {
    const blob = await api.post('/api/tts', { text, rate });
    const audio = new Audio(URL.createObjectURL(blob));
    currentAudio = audio;
    await audio.play();
    await new Promise((r) => { audio.onended = r; audio.onerror = r; });
  } catch (e) {
    toast(e.name === 'NotAllowedError' ? 'Браузер заблокировал автовоспроизведение: кликните по странице и нажмите 🔊.' : 'Озвучка: ' + e.message, true, 8000);
  }
}
