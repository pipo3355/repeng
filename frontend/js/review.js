import { api, esc, h, toast } from './api.js';
import { speak } from './speech.js';

const $ = (id) => document.getElementById(id);
let queue = [];

export function initReview() {
  $('vocabReload').onclick = loadVocab;
  $('exGen').onclick = loadExercises;
  $('addWordBtn').onclick = async () => {
    const word = $('newWord').value.trim();
    if (!word) return;
    await api.post('/api/vocab', { word, translation: $('newTranslation').value.trim(), context: $('newContext').value.trim() });
    $('newWord').value = $('newTranslation').value = $('newContext').value = '';
    toast('Добавлено');
    loadVocab();
  };
}

export async function loadVocab() {
  try {
    queue = (await api.get('/api/review/vocab')).items;
  } catch (e) { toast(e.message, true); queue = []; }
  showCard();
}

function showCard() {
  const box = $('vocabCard');
  const c = queue[0];
  if (!c) {
    box.innerHTML = '<p class="muted">На сегодня всё повторено 🎉<br>Новые слова появляются из разговоров с репетитором.</p>';
    return;
  }
  box.innerHTML = `
    <div class="muted" style="font-size:13px">осталось: ${queue.length}</div>
    <div class="word">${esc(c.word)} <button class="icon-btn" data-say>🔊</button></div>
    <div class="ans hidden">
      <div style="font-size:18px">${esc(c.translation || '—')}</div>
      ${c.context ? `<div class="ctx">${esc(c.context)}</div>` : ''}
    </div>
    <button class="primary" data-show>Показать перевод</button>
    <div class="grades hidden">
      <button data-q="1">Не помню</button>
      <button data-q="3">С трудом</button>
      <button data-q="4">Помню</button>
      <button data-q="5">Легко</button>
    </div>
    <button class="icon-btn danger" data-del style="margin-top:6px">удалить слово</button>`;
  box.querySelector('[data-say]').onclick = () => speak(c.word);
  box.querySelector('[data-show]').onclick = (e) => {
    e.target.classList.add('hidden');
    box.querySelector('.ans').classList.remove('hidden');
    box.querySelector('.grades').classList.remove('hidden');
    if (c.context) speak(c.context);
  };
  box.querySelectorAll('[data-q]').forEach((b) => b.onclick = async () => {
    const q = Number(b.dataset.q);
    await api.post(`/api/review/vocab/${c.id}`, { quality: q });
    queue.shift();
    if (q < 3) queue.push(c); // show again later in this round
    showCard();
  });
  box.querySelector('[data-del]').onclick = async () => {
    await api.del(`/api/vocab/${c.id}`);
    queue.shift();
    showCard();
  };
}

async function loadExercises() {
  const btn = $('exGen'), list = $('exList');
  btn.disabled = true; btn.textContent = 'Составляю…';
  try {
    const r = await api.post('/api/review/exercises');
    if (!r.items.length) {
      list.innerHTML = '<p class="muted">Пока нет накопленных ошибок. Поговорите с репетитором, и здесь появятся упражнения.</p>';
      return;
    }
    list.innerHTML = '';
    r.items.forEach((it) => list.append(exercise(it)));
  } catch (e) {
    toast(e.message, true, 7000);
  } finally {
    btn.disabled = false; btn.textContent = 'Дать упражнения';
  }
}

function exercise(it) {
  const el = h(`<div class="exercise">
    <div class="task">${esc(it.task)}</div>
    <div class="row"><input placeholder="Ваш ответ"><button data-check>Проверить</button></div>
    <div class="answer hidden"></div></div>`);
  const input = el.querySelector('input');
  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9' ]/g, '').replace(/\s+/g, ' ').trim();
  const check = async () => {
    const ok = norm(input.value) === norm(it.answer) || (norm(input.value).length > 0 && norm(it.answer).includes(norm(input.value)) && norm(input.value).length > norm(it.answer).length * 0.6);
    const ans = el.querySelector('.answer');
    ans.classList.remove('hidden');
    ans.innerHTML = `${ok ? '✅ Верно' : '❌ Правильно: <b>' + esc(it.answer) + '</b>'}
      ${it.explanation ? `<div class="muted">${esc(it.explanation)}</div>` : ''}
      ${!ok ? '<button class="small" data-actually>Мой ответ тоже верный</button>' : ''}`;
    el.querySelector('[data-check]').disabled = true;
    input.disabled = true;
    if (it.mistake_id) api.post(`/api/review/mistake/${it.mistake_id}`, { correct: ok }).catch(() => {});
    const actually = ans.querySelector('[data-actually]');
    if (actually) actually.onclick = () => {
      if (it.mistake_id) api.post(`/api/review/mistake/${it.mistake_id}`, { correct: true }).catch(() => {});
      actually.replaceWith('засчитано');
    };
  };
  el.querySelector('[data-check]').onclick = check;
  input.onkeydown = (e) => { if (e.key === 'Enter') check(); };
  return el;
}
