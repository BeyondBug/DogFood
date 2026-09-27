const flash = document.querySelector('#flash');

function notice(message, error = false, link = '') {
  if (!flash) return;
  flash.replaceChildren();
  const text = document.createElement('span');
  text.textContent = message;
  flash.append(text);
  if (link) {
    const anchor = document.createElement('a');
    anchor.href = link;
    anchor.textContent = link;
    anchor.style.marginLeft = '12px';
    flash.append(anchor);
  }
  flash.classList.toggle('flash-error', error);
  flash.hidden = false;
  flash.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let value;
  try { value = await response.json(); } catch { value = {}; }
  if (!response.ok) {
    const detail = value.detail;
    if (Array.isArray(detail)) throw new Error(detail.map(item => item.msg).join('; '));
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`);
  }
  return value;
}

function fields(form) { return Object.fromEntries(new FormData(form)); }
function list(value) { return value.split(',').map(item => item.trim()).filter(Boolean); }
function refresh() { window.location.reload(); }

const setupKey = 'beyondbug-event-setup-draft';
function showSetupStep(form, index) {
  const steps = [...form.querySelectorAll('.setup-step')];
  const step = Math.max(0, Math.min(index, steps.length - 1));
  form.dataset.setupStep = String(step);
  steps.forEach((item, position) => { item.hidden = position !== step; item.classList.toggle('active', position === step); });
  const rail = [...form.closest('.setup-wizard').querySelectorAll('.setup-rail li')];
  rail.forEach((item, position) => { item.classList.toggle('active', position === step); item.classList.toggle('done', position < step); });
  form.closest('.setup-wizard').querySelector('[data-setup-progress]').textContent = `Step ${step + 1} of ${steps.length}`;
  form.querySelector('[data-setup-back]').hidden = step === 0;
  form.querySelector('[data-setup-next]').hidden = step === steps.length - 1;
  form.querySelector('[data-setup-create]').hidden = step !== steps.length - 1;
  if (step === steps.length - 1) {
    const data = fields(form);
    const review = form.querySelector('[data-setup-review]');
    review.replaceChildren();
    for (const [label, value] of [
      ['Event', data.name], ['Submission deadline (UTC)', data.submissions_close],
      ['Tracks', data.tracks], ['Prizes', data.prizes || 'None configured'],
    ]) {
      const row = document.createElement('div');
      const term = document.createElement('strong');
      const description = document.createElement('span');
      term.textContent = label;
      description.textContent = value || 'Not set';
      row.append(term, description);
      review.append(row);
    }
  }
}
function advanceSetupWizard(form) {
  const index = Number(form.dataset.setupStep || 0);
  const step = form.querySelector(`.setup-step[data-step="${index}"]`);
  if (![...step.querySelectorAll('input,textarea,select')].every(input => input.reportValidity())) return;
  if (index === 2 && !list(form.elements.tracks.value).length) {
    form.elements.tracks.setCustomValidity('Add at least one track.');
    form.elements.tracks.reportValidity();
    form.elements.tracks.setCustomValidity('');
    return;
  }
  showSetupStep(form, index + 1);
}
function saveSetupDraft(form) {
  const status = form.querySelector('.setup-save-state');
  try {
    localStorage.setItem(setupKey, JSON.stringify({ values: fields(form), step: Number(form.dataset.setupStep || 0) }));
    status.textContent = 'Draft saved in this browser';
  } catch { status.textContent = 'Draft stays on this page'; }
}
function initSetupWizard() {
  const form = document.querySelector('form[data-setup-wizard]');
  if (!form) return;
  let step = 0;
  try {
    const draft = JSON.parse(localStorage.getItem(setupKey) || '{}');
    for (const [name, value] of Object.entries(draft.values || {})) {
      if (form.elements[name]) form.elements[name].value = value;
    }
    step = Number.isInteger(draft.step) ? Math.max(0, Math.min(draft.step, 3)) : 0;
    for (let index = 0; index < step; index++) {
      const inputs = form.querySelectorAll(`.setup-step[data-step="${index}"] input,.setup-step[data-step="${index}"] textarea`);
      if (![...inputs].every(input => input.checkValidity())) { step = index; break; }
    }
  } catch {}
  showSetupStep(form, step);
  form.addEventListener('input', () => saveSetupDraft(form));
  form.addEventListener('change', () => saveSetupDraft(form));
}
document.addEventListener('DOMContentLoaded', initSetupWizard);
document.addEventListener('keydown', event => {
  const form = event.target.closest('form[data-setup-wizard]');
  if (form && event.key === 'Enter' && event.target.tagName === 'INPUT' && form.dataset.setupStep !== '3') {
    event.preventDefault();
    advanceSetupWizard(form);
    saveSetupDraft(form);
  }
});

const autosaves = new WeakMap();
function scorecardPayload(form, status) {
  const data = fields(form);
  const criteria = {};
  for (const [name, value] of Object.entries(data)) {
    if (name.startsWith('criterion_') && value !== '') criteria[name.slice(10)] = Number(value);
  }
  return { criteria, comment: data.comment || '', status };
}
function scheduleScorecardSave(form) {
  if (form.dataset.autosave !== 'true' || form.dataset.finalizing === 'true') return;
  const state = autosaves.get(form) || {};
  clearTimeout(state.timer);
  const indicator = form.querySelector('.autosave-state');
  indicator.textContent = 'Unsaved changes';
  state.timer = setTimeout(() => {
    indicator.textContent = 'Saving…';
    state.pending = api('PUT', `/api/judge/assignments/${form.dataset.assignment}/scorecard`,
      scorecardPayload(form, 'draft'))
      .then(() => { indicator.textContent = `Saved ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`; })
      .catch(() => { indicator.textContent = 'Draft not saved. Use Save draft to retry.'; });
  }, 1200);
  autosaves.set(form, state);
}
document.addEventListener('input', event => {
  const form = event.target.closest('form[data-action="scorecard"]');
  if (form) scheduleScorecardSave(form);
  if (event.target.closest('#submission-form')) updateSubmissionCheck();
});
document.addEventListener('change', event => {
  if (event.target.closest('#submission-form')) updateSubmissionCheck();
});

const submissionLabels = {
  title: 'Project title', track_id: 'Track', summary: 'Short summary',
  description: 'Full description', repo_url: 'Repository link', demo_url: 'Demo link',
};
function updateSubmissionCheck() {
  const form = document.querySelector('#submission-form');
  if (!form) return;
  const data = fields(form);
  const checks = [...form.querySelectorAll('[data-check]')];
  let completed = 0;
  checks.forEach(item => {
    const key = item.dataset.check;
    const filled = Boolean((data[key] || '').trim());
    if (filled) completed++;
    item.textContent = `${filled ? '✓' : '○'} ${submissionLabels[key]}${item.dataset.required ? ' · required' : ' · recommended'}`;
    item.classList.toggle('check-done', filled);
  });
  form.querySelector('[data-check-count]').textContent = `${completed} / ${checks.length} details added`;
}
function previewLink(anchor, value) {
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Invalid protocol');
    anchor.href = url.href;
    anchor.hidden = false;
  } catch { anchor.hidden = true; anchor.removeAttribute('href'); }
}
document.addEventListener('click', event => {
  if (event.target.closest('[data-setup-next]')) {
    const form = event.target.closest('form[data-setup-wizard]');
    advanceSetupWizard(form);
    saveSetupDraft(form);
  }
  if (event.target.closest('[data-setup-back]')) {
    const form = event.target.closest('form[data-setup-wizard]');
    showSetupStep(form, Number(form.dataset.setupStep || 0) - 1);
    saveSetupDraft(form);
  }
  if (event.target.closest('[data-preview-submission]')) {
    const form = document.querySelector('#submission-form');
    const dialog = document.querySelector('.submission-preview');
    if (!form || !dialog) return;
    const data = fields(form);
    dialog.querySelector('[data-preview="title"]').textContent = data.title || 'Untitled project';
    dialog.querySelector('[data-preview="track"]').textContent = form.querySelector('[name="track_id"]').selectedOptions[0]?.textContent || 'No track';
    dialog.querySelector('[data-preview="summary"]').textContent = data.summary || 'No summary added.';
    dialog.querySelector('[data-preview="description"]').textContent = data.description || 'No full description added.';
    previewLink(dialog.querySelector('[data-preview="repo"]'), data.repo_url);
    previewLink(dialog.querySelector('[data-preview="demo"]'), data.demo_url);
    dialog.showModal();
  }
  if (event.target.closest('[data-close-preview]')) document.querySelector('.submission-preview')?.close();
});
document.addEventListener('DOMContentLoaded', () => {
  updateSubmissionCheck();
  try {
    const message = sessionStorage.getItem('beyondbug-flash');
    if (message) { sessionStorage.removeItem('beyondbug-flash'); notice(message); }
  } catch {}
});

document.addEventListener('submit', async event => {
  const form = event.target.closest('form[data-action]');
  if (!form) return;
  event.preventDefault();
  const action = form.dataset.action;
  const submitter = event.submitter;
  if (action === 'create-event' && form.dataset.setupStep !== '3') {
    advanceSetupWizard(form);
    saveSetupDraft(form);
    return;
  }
  if (action === 'publish' && !window.confirm('Publish final results? Rankings and vote totals become public. Project and score edits lock, and this action is recorded in the audit log.')) return;
  if (action === 'vote' && !window.confirm('Cast this final vote? You cannot change it later.')) return;
  const buttons = [...form.querySelectorAll('button')];
  buttons.forEach(button => { button.disabled = true; });
  try {
    const data = fields(form);
    let result;
    switch (action) {
      case 'login':
      case 'register':
        await api('POST', `/api/auth/${action}`, data);
        window.location.assign(document.querySelector('[data-next]')?.dataset.next || '/dashboard');
        return;
      case 'logout':
        await api('POST', '/api/auth/logout');
        window.location.assign('/');
        return;
      case 'create-event':
        data.tracks = list(data.tracks);
        data.prizes = list(data.prizes || '');
        for (const name of ['registration_open', 'registration_close', 'submissions_open', 'submissions_close', 'judging_open', 'judging_close']) {
          if (data[name]) data[name] = `${data[name]}:00Z`;
          else delete data[name];
        }
        result = await api('POST', '/api/events', data);
        try { localStorage.removeItem(setupKey); } catch {}
        window.location.assign(`/organizer/${result.id}`);
        return;
      case 'event-settings':
        for (const name of ['registration_open', 'registration_close', 'submissions_open', 'submissions_close', 'judging_open', 'judging_close']) {
          data[name] = data[name] ? `${data[name]}:00Z` : null;
        }
        await api('PATCH', `/api/events/${form.dataset.event}`, data);
        refresh(); return;
      case 'join-event':
        await api('POST', `/api/events/${form.dataset.event}/registration`, {});
        window.location.assign(`/workspace/${form.dataset.event}`);
        return;
      case 'create-team':
        await api('POST', `/api/events/${form.dataset.event}/teams`, data);
        refresh(); return;
      case 'team-invite':
        result = await api('POST', `/api/teams/${form.dataset.team}/invites`, {});
        notice('Share this invite link with one teammate:', false, window.location.origin + result.invite_url);
        return;
      case 'project':
        data.status = submitter?.value || 'draft';
        if (form.dataset.project) {
          await api('PUT', `/api/projects/${form.dataset.project}`, data);
        } else {
          data.team_id = form.dataset.team;
          await api('POST', `/api/events/${form.dataset.event}/projects`, data);
        }
        refresh(); return;
      case 'judge-invite':
        result = await api('POST', `/api/events/${form.dataset.event}/judges/invites`, data);
        notice('Share this judge invite with the named email address:', false, window.location.origin + result.invite_url);
        return;
      case 'judge-tracks':
        await api('PUT', `/api/events/${form.dataset.event}/judges/${form.dataset.judge}/tracks`, {
          tracks: [...form.querySelector('[name=tracks]').selectedOptions].map(option => option.value),
        });
        notice('Judge tracks updated.'); return;
      case 'rubric': {
        const criteria = list(data.criteria).map(pair => {
          const [slug, weight] = pair.split(':').map(value => value.trim());
          return { slug: slug.toLowerCase().replace(/\s+/g, '_'), name: slug.replace(/_/g, ' '), weight: Number(weight) };
        });
        await api('PUT', `/api/events/${form.dataset.event}/rubric`, { name: data.name, criteria });
        refresh(); return;
      }
      case 'batch':
        result = await api('POST', `/api/events/${form.dataset.event}/assignments/batch`, {
          reviews_per_project: Number(data.reviews_per_project),
        });
        notice(`${result.created.length} assignments created; ${result.shortages.length} projects still need judges.`);
        setTimeout(refresh, 1400); return;
      case 'scorecard': {
        form.dataset.finalizing = 'true';
        const state = autosaves.get(form);
        if (state) { clearTimeout(state.timer); if (state.pending) await state.pending; }
        const status = submitter?.value || 'draft';
        await api('PUT', `/api/judge/assignments/${form.dataset.assignment}/scorecard`, scorecardPayload(form, status));
        try { sessionStorage.setItem('beyondbug-flash', status === 'submitted' ? 'Review submitted. Continue with the next project.' : 'Draft saved.'); } catch {}
        window.location.assign(`/judge/${form.dataset.event}#next-review`);
        return;
      }
      case 'judge-conflict':
        if (!window.confirm('Report this conflict and remove your assignment?')) return;
        await api('PUT', `/api/events/${form.dataset.event}/judges/${form.dataset.judge}/conflicts/${form.dataset.project}`, data);
        refresh(); return;
      case 'publish':
        await api('POST', `/api/events/${form.dataset.event}/results/publish`, {});
        refresh(); return;
      case 'award-winner':
        await api('PUT', `/api/events/${form.dataset.event}/prizes/${form.dataset.prize}/winner`, {
          project_id: data.project_id,
        });
        refresh(); return;
      case 'issue-certificates':
        result = await api('POST', `/api/events/${form.dataset.event}/certificates/issue`, {});
        notice(`${result.total_created} new certificates issued.`);
        setTimeout(refresh, 1200); return;
      case 'voting-config':
        data.opens_at = `${data.opens_at}:00Z`;
        data.closes_at = `${data.closes_at}:00Z`;
        await api('PUT', `/api/events/${form.dataset.event}/voting`, data);
        refresh(); return;
      case 'voter-invite':
        result = await api('POST', `/api/events/${form.dataset.event}/voter-invites`, data);
        notice('Share this private ballot invite with the named email address:', false, window.location.origin + result.invite_url);
        return;
      case 'vote':
        if (!data.project_id) throw new Error('Choose a project first.');
        await api('POST', `/api/events/${form.dataset.event}/votes`, { project_id: data.project_id });
        refresh(); return;
      case 'comment':
        await api('POST', `/api/projects/${form.dataset.project}/comments`, { body: data.body });
        refresh(); return;
      case 'hide-comment':
        await api('DELETE', `/api/comments/${form.dataset.comment}`);
        refresh(); return;
      case 'accept-invite':
        result = await api('POST', form.dataset.kind === 'team'
          ? `/api/team-invites/${form.dataset.token}/join`
          : form.dataset.kind === 'judge'
            ? `/api/judge-invites/${form.dataset.token}/accept`
            : `/api/voter-invites/${form.dataset.token}/accept`, {});
        window.location.assign(form.dataset.kind === 'team' ? '/dashboard'
          : form.dataset.kind === 'judge' ? `/judge/${result.event_id}`
            : `/vote/${result.event_id}`);
        return;
      default:
        throw new Error('This action is unavailable.');
    }
  } catch (error) {
    notice(error.message || 'Something went wrong.', true);
  } finally {
    buttons.forEach(button => { button.disabled = false; });
  }
});
