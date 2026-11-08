// Rendering of pronunciation results (shared by chat and drill).
import { esc, scoreClass } from './api.js';
import { speak } from './speech.js';

export function scorePill(v, label = '') {
  if (v == null) return '';
  return `<span class="score-pill ${scoreClass(v)}">${label}${Math.round(v)}</span>`;
}

export function pronSummary(p) {
  if (!p) return '';
  const notes = p.notes?.length ? `<div class="pron-notes">${p.notes.map((n) => `<div>👂 ${esc(n)}</div>`).join('')}</div>` : '';
  if (p.approximate) {
    return `<div class="pron-line">Произношение на слух ${scorePill(p.overall, '≈')}
      <span class="muted">· оценка приблизительная</span></div>${notes}`;
  }
  return notes ? pronSummaryMain(p) + notes : pronSummaryMain(p);
}

function pronSummaryMain(p) {
  return `<div class="pron-line">Произношение ${scorePill(p.overall)}
    ${p.accuracy != null ? `<span>точность ${Math.round(p.accuracy)}</span>` : ''}
    ${p.fluency != null ? `<span>беглость ${Math.round(p.fluency)}</span>` : ''}
    ${p.prosody != null ? `<span>интонация ${Math.round(p.prosody)}</span>` : ''}
    <span class="muted">· нажмите на выделенное слово</span></div>`;
}

export function phonemesHtml(word) {
  return `<div class="phonemes">${(word.phonemes || []).map((p) => `
    <div class="ph ${scoreClass(p.score)}" title="${p.heard ? 'прозвучало как /' + esc(p.heard) + '/' : ''}">
      <b>${esc(p.ipa)}</b><small>${Math.round(p.score)}${p.heard ? ' →' + esc(p.heard) : ''}</small>
    </div>`).join('')}</div>`;
}

const ERR = { Omission: 'пропущено', Insertion: 'лишнее слово', Mispronunciation: 'ошибка произношения' };

export function showWordPopover(word, anchor) {
  const pop = document.getElementById('popover');
  pop.innerHTML = `
    <div style="display:flex;justify-content:space-between;gap:10px;align-items:center">
      <b style="font-size:16px">${esc(word.word)}</b> ${scorePill(word.score)}
    </div>
    ${word.error_type && word.error_type !== 'None' ? `<div class="muted" style="font-size:13px">${ERR[word.error_type] || word.error_type}</div>` : ''}
    ${phonemesHtml(word)}
    <div style="margin-top:8px"><button class="small" data-say>🔊 Как правильно</button>
    <button class="small" data-slow>🐢 Медленно</button></div>`;
  pop.querySelector('[data-say]').onclick = () => speak(word.word);
  pop.querySelector('[data-slow]').onclick = () => speak(word.word, { rate: 0.6 });
  const r = anchor.getBoundingClientRect();
  pop.classList.remove('hidden');
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = Math.min(Math.max(8, r.left), window.innerWidth - pw - 8);
  let top = r.bottom + 6;
  if (top + ph > window.innerHeight - 8) top = r.top - ph - 6;
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
}

document.addEventListener('click', (e) => {
  const pop = document.getElementById('popover');
  if (!pop.contains(e.target) && !e.target.closest('[data-word]')) pop.classList.add('hidden');
});

/** Render the user's sentence with weak words highlighted and clickable. */
export function highlightedText(text, pron) {
  if (!pron || !pron.words?.length) return esc(text);
  // Show the scored words in order (they follow the reference/transcript).
  return pron.words.map((w, i) => {
    if (w.error_type === 'Insertion') return '';
    const cls = w.score < 60 || w.error_type === 'Omission' ? 'low' : w.score < 80 ? 'mid' : '';
    return `<span class="w ${cls}" data-word="${i}">${esc(w.word)}</span>`;
  }).join(' ');
}

export function bindWordClicks(container, pron) {
  container.querySelectorAll('[data-word]').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      showWordPopover(pron.words[Number(el.dataset.word)], el);
    });
  });
}
