import { api, esc, h, state, toast } from './api.js';
import { Recorder } from './recorder.js';
import { speak, stopSpeaking } from './speech.js';
import { phonemesHtml, pronSummary, scorePill } from './pron_view.js';

const $ = (id) => document.getElementById(id);
let active = null; // {recorder, btn}

export function initDrill() {
  $('drillGen').onclick = generate;
  $('drillAddCustom').onclick = () => {
    const t = $('drillCustom').value.trim();
    if (!t) return;
    $('drillCustom').value = '';
    $('drillList').prepend(item({ text: t }));
  };
}

export function onShowDrill() {
  const prov = state.settings?.pron?.provider;
  const n = $('drillNotice');
  if (!prov || prov === 'none') {
    n.textContent = 'Оценка произношения выключена. Включите Azure или локальную модель в «Настройках», иначе фразы можно только слушать.';
    n.classList.remove('hidden');
  } else n.classList.add('hidden');
}

async function generate() {
  const btn = $('drillGen');
  btn.disabled = true; btn.textContent = 'Подбираю…';
  try {
    const r = await api.post('/api/drill/generate?n=6');
    $('drillList').innerHTML = '';
    r.items.forEach((it) => $('drillList').append(item(it)));
  } catch (e) {
    toast(e.message, true, 7000);
  } finally {
    btn.disabled = false; btn.textContent = 'Подобрать фразы';
  }
}

function item(it) {
  const el = h(`<div class="card drill-item">
    <div class="text">${esc(it.text)}</div>
    ${it.focus || it.tip ? `<div class="focus">${it.focus ? `<b>${esc(it.focus)}</b> ` : ''}${esc(it.tip || '')}</div>` : ''}
    <div class="row">
      <button data-a="say">🔊 Послушать</button>
      <button data-a="slow">🐢 Медленно</button>
      <button class="primary" data-a="rec">🎙 Повторить</button>
    </div>
    <div class="drill-result"></div>
  </div>`);
  el.querySelector('[data-a=say]').onclick = () => speak(it.text);
  el.querySelector('[data-a=slow]').onclick = () => speak(it.text, { rate: 0.7 });
  const recBtn = el.querySelector('[data-a=rec]');
  recBtn.onclick = () => toggleRec(it.text, recBtn, el.querySelector('.drill-result'));
  return el;
}

async function toggleRec(text, btn, out) {
  if (active && active.btn === btn) {
    const { recorder } = active;
    active = null;
    btn.textContent = 'Оцениваю…'; btn.disabled = true; btn.classList.remove('rec');
    const res = await recorder.stop();
    try {
      if (!res?.hadSpeech) { toast('Речь не услышана'); return; }
      const r = await api.form('/api/drill/assess', { reference: text, audio: res.wav });
      render(out, r);
    } catch (e) {
      out.innerHTML = `<div style="color:var(--bad)">${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = '🎙 Ещё раз';
    }
    return;
  }
  if (active) { await active.recorder.stop(); active.btn.textContent = '🎙 Повторить'; active = null; }
  stopSpeaking();
  const recorder = new Recorder();
  try {
    recorder.onAutoStop = () => { if (active?.recorder === recorder) toggleRec(text, btn, out); };
    await recorder.start({ autoStop: true });
    active = { recorder, btn };
    btn.textContent = '⏹ Стоп';
  } catch (e) {
    toast('Нет доступа к микрофону: ' + e.message, true);
  }
}

function render(out, r) {
  out.innerHTML = `${pronSummary(r)}
    ${r.completeness != null ? `<div class="pron-line">полнота ${Math.round(r.completeness)}</div>` : ''}
    <div class="words">${r.words.filter((w) => w.error_type !== 'Insertion').map((w) => `
      <div class="word-card">
        <div class="wt">${esc(w.word)} ${scorePill(w.score)}</div>
        ${w.score < 90 ? phonemesHtml(w) : ''}
      </div>`).join('')}</div>`;
}
