import { api, state, toast } from './api.js';
import { initChat } from './chat.js';
import { initDrill, onShowDrill } from './drill.js';
import { initReview, loadVocab } from './review.js';
import { loadProgress } from './progress.js';
import { loadSettings, renderSettings } from './settings.js';

const views = {
  chat: () => {},
  drill: onShowDrill,
  review: loadVocab,
  progress: loadProgress,
  settings: renderSettings,
};

function show(name) {
  document.querySelectorAll('nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === name));
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === 'view-' + name));
  try { localStorage.setItem('repeng.view', name); } catch {}
  views[name]?.();
}

async function refreshProfile() {
  try {
    const d = await api.get('/api/progress');
    const level = d.profile.level;
    document.getElementById('levelBadge').textContent = level || '—';
    document.getElementById('placementBanner').classList.toggle('hidden', !!level || !state.settings?.llm_profiles?.length);
  } catch {}
}

async function main() {
  try {
    await loadSettings();
  } catch (e) {
    toast('Сервер недоступен: ' + e.message, true, 10000);
    return;
  }
  document.querySelectorAll('nav button').forEach((b) => b.onclick = () => show(b.dataset.view));
  initChat({ onEnd: refreshProfile });
  initDrill();
  initReview();
  document.addEventListener('settings-changed', refreshProfile);
  document.addEventListener('profile-changed', refreshProfile);

  let start = 'chat';
  try { start = localStorage.getItem('repeng.view') || 'chat'; } catch {}
  if (!state.settings.llm_profiles.length) {
    start = 'settings';
    toast('Для начала добавьте подключение к языковой модели', false, 6000);
  }
  show(start);
  refreshProfile();
}

main();
