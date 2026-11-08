import { api, esc, h, toast } from './api.js';

const SERIES = [
  { key: 'grammar', name: 'Грамматика', color: 'var(--s1)' },
  { key: 'vocabulary', name: 'Словарь', color: 'var(--s2)' },
  { key: 'fluency', name: 'Беглость', color: 'var(--s3)' },
  { key: 'pronunciation', name: 'Произношение', color: 'var(--s4)' },
];
const STATUS = { active: 'повторяется', improving: 'улучшается', mastered: 'освоено' };

export async function loadProgress() {
  const root = document.getElementById('progressRoot');
  let d, mem;
  try {
    [d, mem] = await Promise.all([api.get('/api/progress'), api.get('/api/memory')]);
  } catch (e) { toast(e.message, true); return; }
  const p = d.profile;
  const lastPron = [...d.snapshots].reverse().find((s) => s.pronunciation != null)?.pronunciation;
  root.innerHTML = `
    <div class="stats">
      <div class="stat"><div class="v">${esc(p.level || '—')}</div><div class="l">уровень CEFR</div></div>
      <div class="stat"><div class="v">${d.counts.sessions}</div><div class="l">занятий</div></div>
      <div class="stat"><div class="v">${d.counts.vocab}</div><div class="l">слов в словаре · ${d.counts.vocab_due} к повторению</div></div>
      <div class="stat"><div class="v">${lastPron != null ? Math.round(lastPron) : '—'}</div><div class="l">произношение (последнее)</div></div>
    </div>
    <div class="card">
      <h3>Навыки по занятиям</h3>
      <div id="skillChart"></div>
    </div>
    <div class="grid2">
      <div class="card">
        <h3>Звуки (от слабых к сильным)</h3>
        <div id="phonemeBars"></div>
      </div>
      <div class="card">
        <h3>Профиль</h3>
        <div class="stack" id="profileForm">
          <label>Цели<input name="goals" value="${esc(p.goals)}" placeholder="например: собеседование в IT, путешествия"></label>
          <label>Интересы<input name="interests" value="${esc(p.interests)}" placeholder="футбол, игры, программирование…"></label>
          <label>Уровень (можно поправить вручную)
            <select name="level">${['', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2'].map((l) => `<option ${l === (p.level || '') ? 'selected' : ''} value="${l}">${l || '—'}</option>`).join('')}</select></label>
          <button id="saveProfile">Сохранить профиль</button>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>Повторяющиеся ошибки</h3>
      ${d.mistakes.length ? `<table><thead><tr><th>Тип</th><th>Пример → исправление</th><th>Раз</th><th>Статус</th></tr></thead><tbody>
        ${d.mistakes.map((m) => `<tr><td>${esc(m.pattern)}<div class="muted" style="font-size:12px">${esc(m.category)}</div></td>
          <td><del style="color:var(--bad)">${esc(m.example)}</del> → <b>${esc(m.correction)}</b>
          ${m.explanation ? `<div class="muted" style="font-size:12px">${esc(m.explanation)}</div>` : ''}</td>
          <td>${m.count}</td><td><span class="status ${m.status}">${STATUS[m.status] || m.status}</span></td></tr>`).join('')}
      </tbody></table>` : '<p class="muted">Пока пусто.</p>'}
    </div>
    <div class="card">
      <h3>История занятий</h3>
      ${d.sessions.length ? d.sessions.map((s) => `<div class="session-item">
        <b>${new Date(s.started_at).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' })}</b>
        · ${s.mode === 'placement' ? 'вводный тест' : esc(s.topic || 'свободная беседа')} · реплик: ${s.turns}
        <div>${s.summary ? esc(s.summary) : '<span class="muted">без итогов</span>'}</div></div>`).join('') : '<p class="muted">Пока нет занятий.</p>'}
    </div>
    <div class="card">
      <h3>Что репетитор помнит о вас</h3>
      <p class="muted" style="margin-top:0">Этот блок добавляется в начало каждого занятия.</p>
      <div class="memory-box">${esc(mem.context)}</div>
    </div>`;
  lineChart(document.getElementById('skillChart'), d.snapshots);
  phonemeBars(document.getElementById('phonemeBars'), d.phonemes);
  root.querySelector('#saveProfile').onclick = async () => {
    const f = root.querySelector('#profileForm');
    const body = {};
    f.querySelectorAll('[name]').forEach((i) => { body[i.name] = i.value; });
    if (!body.level) delete body.level;
    await api.put('/api/profile', body);
    toast('Профиль сохранён');
    document.dispatchEvent(new Event('profile-changed'));
  };
}

function lineChart(el, snaps) {
  if (snaps.length < 1) { el.innerHTML = '<p class="muted">График появится после первого завершённого занятия.</p>'; return; }
  const W = 860, H = 260, m = { l: 34, r: 96, t: 10, b: 26 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const n = snaps.length;
  const x = (i) => m.l + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
  const y = (v) => m.t + ih - (v / 100) * ih;
  const grid = [0, 25, 50, 75, 100].map((v) => `<line class="gridline" x1="${m.l}" x2="${m.l + iw}" y1="${y(v)}" y2="${y(v)}"/>
    <text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`).join('');
  const step = Math.max(1, Math.ceil(n / 8));
  const xt = snaps.map((s, i) => (i % step === 0 || i === n - 1)
    ? `<text x="${x(i)}" y="${H - 6}" text-anchor="middle">${new Date(s.created_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}</text>` : '').join('');
  // direct labels at the line ends, nudged apart to avoid collisions
  const ends = [];
  const lines = SERIES.map((s) => {
    const pts = snaps.map((d, i) => (d[s.key] == null ? null : [x(i), y(d[s.key]), d[s.key]])).filter(Boolean);
    if (!pts.length) return '';
    const last = pts[pts.length - 1];
    ends.push({ y: last[1], x: last[0], s, v: last[2] });
    const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('');
    const dots = pts.length <= 20 ? pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="${s.color}" stroke="var(--surface)" stroke-width="2"/>`).join('') : '';
    return `<path d="${path}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>${dots}`;
  }).join('');
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
  const labels = ends.map((e) => `<text class="label" x="${m.l + iw + 10}" y="${e.y + 4}">${e.s.name} ${Math.round(e.v)}</text>`).join('');

  el.innerHTML = `
    <div class="legend">${SERIES.map((s) => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join('')}</div>
    <div class="chart-wrap">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Оценки навыков по занятиям">
        <g class="axis">${grid}${xt}</g>${lines}${labels}
        <line class="xhair" y1="${m.t}" y2="${m.t + ih}" stroke="var(--text-2)" stroke-width="1" stroke-dasharray="3 3" visibility="hidden"/>
        <rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" class="hit"/>
      </svg>
      <div class="tooltip hidden"></div>
    </div>`;
  const svg = el.querySelector('svg'), tip = el.querySelector('.tooltip'), xh = el.querySelector('.xhair');
  const hit = el.querySelector('.hit');
  hit.addEventListener('mousemove', (ev) => {
    const r = svg.getBoundingClientRect();
    const px = ((ev.clientX - r.left) / r.width) * W;
    const i = n === 1 ? 0 : Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / iw) * (n - 1))));
    const d = snaps[i];
    xh.setAttribute('x1', x(i)); xh.setAttribute('x2', x(i)); xh.setAttribute('visibility', 'visible');
    tip.innerHTML = `<b>${new Date(d.created_at).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' })}${d.level ? ' · ' + esc(d.level) : ''}</b>` +
      SERIES.map((s) => `<div class="tl"><i style="background:${s.color}"></i>${s.name}: ${d[s.key] == null ? '—' : Math.round(d[s.key])}</div>`).join('');
    tip.classList.remove('hidden');
    const left = (x(i) / W) * r.width;
    tip.style.left = Math.min(left + 12, r.width - tip.offsetWidth) + 'px';
    tip.style.top = '10px';
  });
  hit.addEventListener('mouseleave', () => { tip.classList.add('hidden'); xh.setAttribute('visibility', 'hidden'); });
}

function phonemeBars(el, ph) {
  const list = ph.filter((p) => p.attempts >= 2).slice(0, 14);
  if (!list.length) { el.innerHTML = '<p class="muted">Появится после голосовых занятий или тренировки произношения.</p>'; return; }
  el.innerHTML = `<div class="bars">${list.map((p) => {
    const v = Math.round(p.recent_avg ?? 0);
    const subs = Object.entries(p.substitutions || {}).sort((a, b) => b[1] - a[1]).slice(0, 2);
    return `<div class="bar-row" title="попыток: ${p.attempts}">
      <span class="ipa">/${esc(p.phoneme)}/</span>
      <div class="bar-track"><div class="bar-fill" style="width:${v}%"></div></div>
      <span class="val">${v}</span>
      ${subs.length || p.examples.length ? `<span class="sub">${subs.length ? 'звучит как ' + subs.map(([s]) => '/' + esc(s) + '/').join(', ') : ''}${subs.length && p.examples.length ? ' · ' : ''}${p.examples.length ? esc(p.examples.slice(0, 3).join(', ')) : ''}</span>` : ''}
    </div>`;
  }).join('')}</div>`;
}
