import { api, esc, h, state, toast } from './api.js';
import { Recorder } from './recorder.js';
import { speak, stopSpeaking } from './speech.js';
import { bindWordClicks, highlightedText, pronSummary } from './pron_view.js';

const $ = (id) => document.getElementById(id);
const log = $('chatLog');
let sessionId = null;
let sessionMode = null;
let busy = false;
let recorder = null;
let onSessionEnd = () => {};

export function initChat({ onEnd }) {
  onSessionEnd = onEnd || onSessionEnd;
  $('topicSelect').onchange = () => $('topicCustom').classList.toggle('hidden', $('topicSelect').value !== '__custom');
  $('startSession').onclick = () => startSession('conversation');
  $('startPlacement').onclick = () => { showView('chat'); startSession('placement'); };
  $('endSession').onclick = endSession;
  $('composer').onsubmit = (e) => { e.preventDefault(); sendText(); };
  $('micBtn').onclick = toggleMic;

  // hold space to talk (when not typing in a field)
  let spaceDown = false;
  document.addEventListener('keydown', (e) => {
    if (e.code !== 'Space' || spaceDown || !sessionId || isTyping(e)) return;
    if (!document.getElementById('view-chat').classList.contains('active')) return;
    e.preventDefault(); spaceDown = true;
    if (!recorder?.recording) toggleMic();
  });
  document.addEventListener('keyup', (e) => {
    if (e.code !== 'Space' || !spaceDown) return;
    spaceDown = false;
    if (recorder?.recording) toggleMic();
  });
  window.addEventListener('beforeunload', () => {
    if (sessionId) navigator.sendBeacon(`/api/session/${sessionId}/end`);
  });
}

function isTyping(e) {
  const t = e.target;
  return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}

function showView(name) { document.querySelector(`nav button[data-view="${name}"]`)?.click(); }

function setActive(active) {
  $('composer').classList.toggle('disabled', !active);
  $('endSession').classList.toggle('hidden', !active);
  $('startSession').classList.toggle('hidden', active);
  $('topicSelect').disabled = active;
  $('topicCustom').disabled = active;
  $('modeTag').classList.toggle('hidden', !active);
}

async function startSession(mode) {
  if (sessionId) await endSession();
  let topic = '';
  if (mode === 'conversation') {
    topic = $('topicSelect').value === '__custom' ? $('topicCustom').value.trim() : $('topicSelect').value;
  }
  log.innerHTML = '';
  const typing = addTyping();
  $('startSession').disabled = true;
  try {
    const r = await api.post('/api/session/start', { mode, topic });
    sessionId = r.session_id;
    sessionMode = mode;
    $('modeTag').textContent = mode === 'placement' ? 'Вводный тест' : (topic || 'Свободная беседа');
    setActive(true);
    typing.remove();
    addAssistant(r.reply);
    if ($('autoSpeak').checked) speak(r.reply);
    $('textInput').focus();
  } catch (e) {
    typing.remove();
    log.append(h(`<div class="empty-hint">Не удалось начать: ${esc(e.message)}</div>`));
    toast(e.message, true, 7000);
  } finally {
    $('startSession').disabled = false;
  }
}

async function endSession() {
  if (!sessionId) return;
  const sid = sessionId;
  sessionId = null;
  stopSpeaking();
  if (recorder?.recording) await recorder.stop();
  setActive(false);
  const note = h(`<div class="feedback typing">Сохраняю итоги занятия в память…</div>`);
  log.append(note); scrollDown();
  try {
    const r = await api.post(`/api/session/${sid}/end`);
    note.classList.remove('typing');
    note.innerHTML = r.summary ? `<b>Итоги занятия:</b> ${esc(r.summary)}` : 'Сессия закрыта.';
  } catch (e) {
    note.textContent = 'Не удалось сохранить итоги: ' + e.message;
  }
  scrollDown();
  onSessionEnd();
}

function scrollDown() { log.scrollTop = log.scrollHeight; }

function addTyping() {
  const el = h(`<div class="msg assistant"><div class="bubble typing">печатает…</div></div>`);
  log.append(el); scrollDown();
  return el;
}

function addAssistant(text, tip = '') {
  const el = h(`<div class="msg assistant">
    <div class="bubble">${esc(text)}</div>
    ${tip ? `<div class="tip">💡 ${esc(tip)}</div>` : ''}
    <div class="actions">
      <button class="icon-btn" data-a="say">🔊 Повторить</button>
      <button class="icon-btn" data-a="slow">🐢 Медленнее</button>
    </div></div>`);
  el.querySelector('[data-a=say]').onclick = () => speak(text);
  el.querySelector('[data-a=slow]').onclick = () => speak(text, { rate: 0.75 });
  log.append(el); scrollDown();
}

function addUser(text, pending = false) {
  const el = h(`<div class="msg user"><div class="bubble">${pending ? '<span class="typing">распознаю…</span>' : esc(text)}</div></div>`);
  log.append(el); scrollDown();
  return el;
}

function fillUser(el, r) {
  const bubble = el.querySelector('.bubble');
  bubble.innerHTML = highlightedText(r.transcript, r.pron);
  if (r.pron) bindWordClicks(bubble, r.pron);
  const parts = [];
  if (r.corrections?.length) {
    parts.push(r.corrections.map((c) => `
      <div class="corr"><del>${esc(c.original)}</del> → <ins>${esc(c.corrected)}</ins>
      ${c.explanation ? `<div class="expl">${esc(c.explanation)}</div>` : ''}</div>`).join(''));
  }
  if (r.pron) parts.push(pronSummary(r.pron));
  if (r.pron_error) parts.push(`<div class="pron-line muted">Оценка произношения недоступна: ${esc(r.pron_error)}</div>`);
  if (r.new_vocab?.length) {
    parts.push(`<div class="pron-line">📘 В словарь: ${r.new_vocab.map((v) => `<b>${esc(v.word)}</b>${v.translation ? ' (' + esc(v.translation) + ')' : ''}`).join(', ')}</div>`);
  }
  if (parts.length) el.append(h(`<div class="feedback">${parts.join('')}</div>`));
}

async function sendTurn({ text = '', wav = null, el }) {
  busy = true;
  const typing = addTyping();
  try {
    const r = await api.form(`/api/session/${sessionId}/turn`, { text, audio: wav });
    typing.remove();
    if (!r.transcript) {
      el.querySelector('.bubble').innerHTML = `<span class="typing">${esc(r.error || 'не распознано')}</span>`;
      return;
    }
    fillUser(el, r);
    addAssistant(r.reply, r.pron_tip);
    if ($('autoSpeak').checked) speak(r.reply);
    if (r.ended) {
      sessionId = null;
      setActive(false);
      if (r.placement_result) {
        const p = r.placement_result;
        log.append(h(`<div class="feedback"><b>Результат теста: уровень ${esc(p.level || '?')}</b><br>
          ${p.summary ? esc(p.summary) + '<br>' : ''}
          ${p.strengths ? '<b>Сильные стороны:</b> ' + esc(p.strengths) + '<br>' : ''}
          ${p.weaknesses ? '<b>Над чем работать:</b> ' + esc(p.weaknesses) : ''}</div>`));
      }
      scrollDown();
      onSessionEnd();
    }
  } catch (e) {
    typing.remove();
    el.querySelector('.bubble').textContent = text || '(голосовое сообщение)';
    el.append(h(`<div class="feedback" style="color:var(--bad)">Ошибка: ${esc(e.message)}</div>`));
    toast(e.message, true, 7000);
  } finally {
    busy = false;
    scrollDown();
  }
}

function sendText() {
  const text = $('textInput').value.trim();
  if (!text || !sessionId || busy) return;
  $('textInput').value = '';
  stopSpeaking();
  sendTurn({ text, el: addUser(text) });
}

async function toggleMic() {
  if (!sessionId) return;
  const btn = $('micBtn');
  if (recorder?.recording) {
    btn.classList.remove('rec');
    btn.classList.add('busy');
    $('recStatus').textContent = '';
    const res = await recorder.stop();
    btn.classList.remove('busy');
    if (!res || !res.hadSpeech || res.duration < 0.4) { toast('Речь не услышана — попробуйте ещё раз'); return; }
    const browserSTT = state.settings?.stt?.provider === 'browser';
    if (browserSTT && !res.text) {
      toast('Браузер не распознал речь. Нужен Chrome/Edge, либо выберите серверное распознавание в настройках.', true, 7000);
      return;
    }
    sendTurn({ text: browserSTT ? res.text : '', wav: res.wav, el: addUser('', true) });
    return;
  }
  if (busy) return;
  stopSpeaking();
  recorder = new Recorder();
  try {
    recorder.onAutoStop = () => { if (recorder.recording) toggleMic(); };
    await recorder.start({ autoStop: $('autoStop').checked, browserSTT: state.settings?.stt?.provider === 'browser' });
    btn.classList.add('rec');
    $('recStatus').textContent = 'Запись… говорите по-английски';
  } catch (e) {
    toast('Нет доступа к микрофону: ' + e.message, true, 7000);
  }
}
