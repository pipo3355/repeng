import { api, esc, h, state, toast } from './api.js';
import { englishVoices, speak } from './speech.js';

let draft = null;

export async function loadSettings() {
  state.settings = await api.get('/api/settings');
  return state.settings;
}

export function renderSettings() {
  draft = structuredClone(state.settings);
  const root = document.getElementById('settingsRoot');
  const s = draft;
  root.innerHTML = `
    <div class="card">
      <div class="section-head small"><h2>Языковые модели (репетитор)</h2>
        <div class="row"><select id="presetSel">${Object.entries(s.presets).map(([k, p]) => `<option value="${k}">${esc(p.name)}</option>`).join('')}</select>
        <button id="addProfile">+ Добавить</button></div></div>
      <p class="muted" style="margin-top:0">OmniRoute, OpenRouter, Ollama, LM Studio и другие шлюзы подключаются как «OpenAI-совместимые»: нужны адрес <code>/v1</code>, ключ и имя модели. Anthropic подключается напрямую.</p>
      <div id="profiles"></div>
      <div class="form-grid" style="margin-top:10px">
        <label>Основная модель</label><select id="activeLlm"></select>
        <label>Для фоновых задач</label><select id="bgLlm"></select>
        <div class="hint">Итоги занятий, упражнения, фразы для тренировки. Можно выбрать модель подешевле.</div>
      </div>
    </div>

    <div class="card">
      <h2>Распознавание речи</h2>
      <div class="form-grid">
        <label>Провайдер</label>
        <select id="sttProvider">
          <option value="browser">Браузер (Chrome/Edge, бесплатно)</option>
          <option value="openai_compat">Whisper API (OpenAI / Groq / свой сервер)</option>
          <option value="audio_llm">Аудио-LLM (Gemini, MiMo… через профиль)</option>
          <option value="azure">Azure Speech</option>
          <option value="local_whisper">Локальный Whisper (офлайн)</option>
        </select>
        <div class="hint">Для оценки акцента лучше Whisper/Azure: браузер «додумывает» слова. Groq даёт Whisper бесплатно.</div>
        <label class="stt-oc">Base URL</label><input class="stt-oc" id="sttBase">
        <label class="stt-oc">API key</label><input class="stt-oc" id="sttKey" type="password">
        <label class="stt-oc">Модель</label><input class="stt-oc" id="sttModel">
        <label class="stt-llm">Профиль аудио-модели</label><select class="stt-llm" id="sttLlm"></select>
        <div class="hint stt-llm">Создайте отдельный профиль LLM с аудио-моделью (например gemini-3.8-flash) — он может отличаться от модели-репетитора.</div>
        <label class="stt-local">Модель faster-whisper</label>
        <select class="stt-local" id="sttLocal">${['base.en', 'small.en', 'medium.en', 'large-v3'].map((m) => `<option>${m}</option>`).join('')}</select>
        <label></label><div class="row"><button data-test="stt">Проверить</button><span class="test-result" id="test-stt"></span></div>
      </div>
    </div>

    <div class="card">
      <h2>Оценка произношения и акцента</h2>
      <div class="form-grid">
        <label>Провайдер</label>
        <select id="pronProvider">
          <option value="none">Выключено</option>
          <option value="azure">Azure Pronunciation Assessment (точнее, есть интонация)</option>
          <option value="local">Локальная фонемная модель (офлайн, wav2vec2)</option>
          <option value="audio_llm">Аудио-LLM «на слух» (приблизительно)</option>
        </select>
        <div class="hint">Azure: бесплатный тариф F0 даёт ~5 часов аудио в месяц. Локальная модель требует <code>pip install -r requirements-local.txt</code> и скачает ~1.2 ГБ при первом запуске.</div>
        <label class="pron-notes">Замечания аудио-LLM</label>
        <label class="pron-notes" style="color:var(--text)"><input type="checkbox" id="pronNotes"> дополнительно получать словесные советы от аудио-модели</label>
        <label class="pron-llm">Профиль аудио-модели</label><select class="pron-llm" id="pronLlm"></select>
        <div class="hint pron-llm">Аудио-LLM объясняет ошибки словами, но её баллы нестабильны: в статистику звуков они не идут.</div>
        <label>Azure Speech key</label><input id="azKey" type="password">
        <label>Azure region</label><input id="azRegion" placeholder="westeurope, eastus…">
        <label>Акцент-эталон</label>
        <select id="accent"><option value="en-US">Американский (en-US)</option><option value="en-GB">Британский (en-GB)</option></select>
        <label></label><div class="row"><button data-test="pron">Проверить</button><span class="test-result" id="test-pron"></span></div>
      </div>
    </div>

    <div class="card">
      <h2>Озвучка</h2>
      <div class="form-grid">
        <label>Провайдер</label>
        <select id="ttsProvider">
          <option value="browser">Браузер (бесплатно)</option>
          <option value="azure">Azure Neural TTS (ключ из блока выше)</option>
          <option value="openai_compat">OpenAI-совместимый /audio/speech</option>
        </select>
        <label class="tts-az">Голос Azure (англ.)</label><input class="tts-az" id="ttsAzVoice">
        <label class="tts-az">Голос Azure (рус.)</label><input class="tts-az" id="ttsAzRuVoice" placeholder="ru-RU-SvetlanaNeural">
        <div class="hint">Русские вставки в ответах читаются русским голосом, английский текст — английским. В браузерной озвучке без русского голоса в системе русские куски пропускаются.</div>
        <label class="tts-oc">Base URL</label><input class="tts-oc" id="ttsBase">
        <label class="tts-oc">API key</label><input class="tts-oc" id="ttsKey" type="password">
        <label class="tts-oc">Модель</label><input class="tts-oc" id="ttsModel">
        <label class="tts-oc">Голос</label><input class="tts-oc" id="ttsVoice">
        <label>Скорость</label><input id="ttsRate" type="range" min="0.6" max="1.3" step="0.05">
        <label></label><div class="row"><button data-test="tts">Проверить</button><span class="test-result" id="test-tts"></span></div>
      </div>
    </div>

    <div class="card">
      <h2>Репетитор</h2>
      <div class="form-grid">
        <label>Язык объяснений</label>
        <select id="explainLang"><option value="ru">Русский</option><option value="en">English</option></select>
      </div>
    </div>
    <div class="row"><button class="primary" id="saveSettings">Сохранить настройки</button></div>`;

  const v = (id) => root.querySelector('#' + id);
  v('sttProvider').value = s.stt.provider; v('sttBase').value = s.stt.base_url; v('sttKey').value = s.stt.api_key;
  v('sttModel').value = s.stt.model; v('sttLocal').value = s.stt.local_model;
  v('pronProvider').value = s.pron.provider; v('pronNotes').checked = !!s.pron.llm_notes; v('azKey').value = s.azure.key; v('azRegion').value = s.azure.region;
  v('accent').value = s.tutor.accent || 'en-US';
  v('ttsProvider').value = s.tts.provider; v('ttsAzVoice').value = s.tts.azure_voice; v('ttsAzRuVoice').value = s.tts.azure_ru_voice || ''; v('ttsBase').value = s.tts.base_url;
  v('ttsKey').value = s.tts.api_key; v('ttsModel').value = s.tts.model; v('ttsVoice').value = s.tts.voice; v('ttsRate').value = s.tts.rate;
  v('explainLang').value = s.tutor.explain_lang;

  const toggles = () => {
    root.querySelectorAll('.stt-oc').forEach((e) => e.classList.toggle('hidden', v('sttProvider').value !== 'openai_compat'));
    root.querySelectorAll('.stt-llm').forEach((e) => e.classList.toggle('hidden', v('sttProvider').value !== 'audio_llm'));
    const pp = v('pronProvider').value;
    root.querySelectorAll('.pron-notes').forEach((e) => e.classList.toggle('hidden', !['azure', 'local'].includes(pp)));
    root.querySelectorAll('.pron-llm').forEach((e) => e.classList.toggle('hidden', !(pp === 'audio_llm' || (['azure', 'local'].includes(pp) && v('pronNotes').checked))));
    root.querySelectorAll('.stt-local').forEach((e) => e.classList.toggle('hidden', v('sttProvider').value !== 'local_whisper'));
    root.querySelectorAll('.tts-oc').forEach((e) => e.classList.toggle('hidden', v('ttsProvider').value !== 'openai_compat'));
    root.querySelectorAll('.tts-az').forEach((e) => e.classList.toggle('hidden', v('ttsProvider').value !== 'azure'));
  };
  ['sttProvider', 'ttsProvider', 'pronProvider', 'pronNotes'].forEach((id) => v(id).addEventListener('change', toggles));
  toggles();

  renderProfiles();
  v('addProfile').onclick = () => {
    const p = s.presets[v('presetSel').value];
    s.llm_profiles.push({ id: '', name: p.name, kind: p.kind, base_url: p.base_url, api_key: '', model: p.model, headers: '', effort: 'low', fallbacks: true });
    renderProfiles();
  };

  const collect = () => {
    readProfiles();
    s.active_llm = v('activeLlm').value || null;
    s.background_llm = v('bgLlm').value || null;
    Object.assign(s.stt, { provider: v('sttProvider').value, base_url: v('sttBase').value, api_key: v('sttKey').value, model: v('sttModel').value, local_model: v('sttLocal').value, llm_profile: v('sttLlm').value || null });
    Object.assign(s.pron, { provider: v('pronProvider').value, llm_notes: v('pronNotes').checked, llm_profile: v('pronLlm').value || null });
    Object.assign(s.azure, { key: v('azKey').value, region: v('azRegion').value.trim() });
    Object.assign(s.tts, { provider: v('ttsProvider').value, azure_voice: v('ttsAzVoice').value, azure_ru_voice: v('ttsAzRuVoice').value, base_url: v('ttsBase').value,
      api_key: v('ttsKey').value, model: v('ttsModel').value, voice: v('ttsVoice').value, rate: Number(v('ttsRate').value) });
    Object.assign(s.tutor, { explain_lang: v('explainLang').value, accent: v('accent').value });
  };
  const save = async (quiet = false) => {
    collect();
    const hadNew = s.llm_profiles.some((p) => !p.id);
    state.settings = await api.put('/api/settings', s);
    // pick up ids the server assigned to new profiles
    state.settings.llm_profiles.forEach((p, i) => { if (s.llm_profiles[i]) s.llm_profiles[i].id = p.id; });
    s.active_llm = state.settings.active_llm;
    s.background_llm = state.settings.background_llm;
    if (hadNew) renderProfiles();
    if (!quiet) toast('Настройки сохранены');
    document.dispatchEvent(new Event('settings-changed'));
  };
  v('saveSettings').onclick = async () => { try { await save(); renderSettings(); } catch (e) { toast(e.message, true); } };

  root.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-test]');
    if (!t) return;
    const target = t.dataset.test;
    const outId = '#test-' + (target === 'llm' ? 'llm-' + t.dataset.idx : target);
    let out = root.querySelector(outId);
    out.className = 'test-result'; out.textContent = 'Сохраняю и проверяю…';
    try {
      await save(true);
      out = root.querySelector(outId);
      const body = { target };
      if (target === 'llm') body.profile_id = state.settings.llm_profiles[Number(t.dataset.idx)]?.id;
      const r = await api.post('/api/settings/test', body);
      let msg = r.message;
      if (target === 'tts') {
        if (state.settings.tts.provider === 'browser') {
          const voices = await englishVoices();
          msg = voices.length
            ? `Английских голосов: ${voices.length} (${voices.slice(0, 3).map((x) => x.name).join(', ')}…). Сейчас прозвучит фраза.`
            : 'Английских голосов в системе нет — прозвучит голос по умолчанию.';
        }
        speak('Hello! If you can hear me, the voice works.');
      }
      out.className = 'test-result ok'; out.textContent = '✓ ' + msg;
    } catch (err) {
      out = root.querySelector(outId);
      out.className = 'test-result err'; out.textContent = '✗ ' + err.message;
    }
  });
}

function renderProfiles() {
  const s = draft;
  const box = document.getElementById('profiles');
  if (!s.llm_profiles.length) box.innerHTML = '<p class="muted">Нет ни одного профиля. Выберите пресет и нажмите «Добавить».</p>';
  else box.innerHTML = s.llm_profiles.map((p, i) => `
    <div class="profile-card ${p.id && p.id === s.active_llm ? 'active-p' : ''}" data-idx="${i}">
      <div class="form-grid">
        <label>Название</label><input data-f="name" value="${esc(p.name)}">
        <label>Тип</label><select data-f="kind">
          <option value="openai_compat" ${p.kind === 'openai_compat' ? 'selected' : ''}>OpenAI-совместимый</option>
          <option value="anthropic" ${p.kind === 'anthropic' ? 'selected' : ''}>Anthropic (напрямую)</option></select>
        <label>Base URL</label><input data-f="base_url" value="${esc(p.base_url)}" placeholder="${p.kind === 'anthropic' ? 'по умолчанию api.anthropic.com' : 'http://localhost:20128/v1'}">
        <label>API key</label><input data-f="api_key" type="password" value="${esc(p.api_key)}" placeholder="${p.kind === 'anthropic' ? 'sk-ant-… (или переменная ANTHROPIC_API_KEY)' : 'можно пусто для локальных'}">
        <label>Модель</label><input data-f="model" value="${esc(p.model)}" placeholder="имя модели в этом сервисе">
        ${p.kind === 'anthropic' ? `
        <label>Effort</label><select data-f="effort">${['low', 'medium', 'high', 'none'].map((x) => `<option ${x === (p.effort || 'low') ? 'selected' : ''}>${x}</option>`).join('')}</select>
        <div class="hint">low — быстрые ответы в разговоре; none — не передавать (для старых моделей).</div>
        <label>Refusal fallback</label><label style="color:var(--text)"><input type="checkbox" data-f="fallbacks" ${p.fallbacks !== false ? 'checked' : ''}> при отказе модели повторить запрос на резервной модели</label>` : `
        <label>Доп. заголовки</label><input data-f="headers" value="${esc(typeof p.headers === 'string' ? p.headers : '')}" placeholder="Header: value (необязательно)">`}
        <label></label><div class="row">
          <button data-test="llm" data-idx="${i}">Проверить</button>
          <button class="danger" data-del="${i}">Удалить</button>
          <span class="test-result" id="test-llm-${i}"></span></div>
      </div>
    </div>`).join('');
  box.querySelectorAll('[data-f=kind]').forEach((sel) => sel.onchange = () => { readProfiles(); renderProfiles(); });
  box.querySelectorAll('[data-del]').forEach((b) => b.onclick = () => { readProfiles(); s.llm_profiles.splice(Number(b.dataset.del), 1); renderProfiles(); });
  const opts = (withDefault) => (withDefault ? '<option value="">= основная</option>' : '') +
    s.llm_profiles.map((p) => `<option value="${esc(p.id)}" ${p.id ? '' : 'disabled'}>${esc(p.name)}${p.model ? ' · ' + esc(p.model) : ''}${p.id ? '' : ' (сохраните)'}</option>`).join('');
  const a = document.getElementById('activeLlm'), b = document.getElementById('bgLlm');
  a.innerHTML = opts(false); b.innerHTML = opts(true);
  a.value = s.active_llm || ''; b.value = s.background_llm || '';
  // audio-model pickers: only OpenAI-compatible profiles can take audio input
  const audioOpts = '<option value="">— выберите —</option>' + s.llm_profiles.filter((p) => p.kind !== 'anthropic')
    .map((p) => `<option value="${esc(p.id)}" ${p.id ? '' : 'disabled'}>${esc(p.name)}${p.model ? ' · ' + esc(p.model) : ''}${p.id ? '' : ' (сохраните)'}</option>`).join('');
  for (const [id, cur] of [['sttLlm', s.stt.llm_profile], ['pronLlm', s.pron.llm_profile]]) {
    const el = document.getElementById(id);
    if (el) { el.innerHTML = audioOpts; el.value = cur || ''; }
  }
}

function readProfiles() {
  document.querySelectorAll('#profiles .profile-card').forEach((card) => {
    const p = draft.llm_profiles[Number(card.dataset.idx)];
    card.querySelectorAll('[data-f]').forEach((i) => { p[i.dataset.f] = i.type === 'checkbox' ? i.checked : i.value; });
  });
}
