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

document.addEventListener('submit', async event => {
  const form = event.target.closest('form[data-action]');
  if (!form) return;
  event.preventDefault();
  const action = form.dataset.action;
  const submitter = event.submitter;
  if (action === 'publish' && !window.confirm('Publish these results for everyone? Scores will be locked.')) return;
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
        window.location.assign(`/organizer/${result.id}`);
        return;
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
        const criteria = {};
        for (const [name, value] of Object.entries(data)) {
          if (name.startsWith('criterion_') && value !== '') criteria[name.slice(10)] = Number(value);
        }
        await api('PUT', `/api/judge/assignments/${form.dataset.assignment}/scorecard`, {
          criteria, comment: data.comment || '', status: submitter?.value || 'draft',
        });
        refresh(); return;
      }
      case 'judge-conflict':
        if (!window.confirm('Report this conflict and remove your assignment?')) return;
        await api('PUT', `/api/events/${form.dataset.event}/judges/${form.dataset.judge}/conflicts/${form.dataset.project}`, data);
        refresh(); return;
      case 'publish':
        await api('POST', `/api/events/${form.dataset.event}/results/publish`, {});
        refresh(); return;
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
