const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let documentRecords = [];
let currentObjectUrl = null;
let analyticsLoaded = false;
let activeQuestionId = null;
let analyticsChartOffset = 0;
let analyticsQuestionPage = 1;

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: 'same-origin', ...options });
  if (response.status === 401) {
    window.location.assign('/login');
    throw new Error('Please sign in again.');
  }
  return response;
}

async function boot() {
  try {
    const response = await api('/api/auth/me');
    const user = await response.json();
    $('#user-name').textContent = user.username;
    $('#user-role').textContent = user.role;
    $('#user-avatar').textContent = user.username.slice(0, 1).toUpperCase();
    if (user.role === 'admin') $('#analytics-nav').classList.remove('d-none');
    await Promise.all([loadDocuments(), loadRecentQuestions()]);
  } catch (error) {
    if (error.message !== 'Please sign in again.') console.error(error);
  }
}

function selectView(view) {
  $$('.app-nav [data-view]').forEach((item) => item.classList.toggle('active', item.dataset.view === view));
  $$('.view-panel').forEach((item) => {
    const active = item.id === `view-${view}`;
    item.classList.toggle('active', active);
    item.classList.toggle('d-none', !active);
  });
  if (view === 'analytics') loadAnalytics();
  if (view === 'documents') loadDocuments();
  if (view === 'history') loadQuestionHistory();
}

$$('.app-nav [data-view]').forEach((item) => item.addEventListener('click', () => selectView(item.dataset.view)));
$$('[data-view-link]').forEach((item) => item.addEventListener('click', () => selectView(item.dataset.viewLink)));

$('#logout-button').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' });
  window.location.assign('/');
});

async function loadDocuments() {
  const tbody = $('#documents-table');
  try {
    const response = await api('/api/documents');
    if (!response.ok) throw new Error('Could not load documents.');
    const data = await response.json();
    documentRecords = data.documents || [];
    $('#document-count-label').textContent = `${documentRecords.length} indexed`;
    $('#stat-docs').textContent = documentRecords.length;
    $('#stat-chunks').textContent = documentRecords.reduce((sum, doc) => sum + doc.chunk_count, 0).toLocaleString();
    $('#stat-families').textContent = new Set(documentRecords.map((doc) => doc.document_type)).size;
    $('#search-scope').innerHTML = '<option value="">All documents</option>' + documentRecords.map((doc) =>
      `<option value="${escapeAttribute(doc.doc_id)}">${escapeHtml(displayDocumentTitle(doc))}</option>`).join('');
    $('#documents-empty').classList.toggle('d-none', documentRecords.length > 0);
    tbody.innerHTML = documentRecords.map((doc) => `
      <tr data-search="${escapeAttribute(`${doc.title} ${doc.filename} ${doc.document_type}`.toLowerCase())}">
        <td><button class="document-title-button" data-open-doc="${escapeAttribute(doc.doc_id)}" title="${escapeAttribute(doc.filename)}">${escapeHtml(displayDocumentTitle(doc))}</button></td>
        <td><span class="type-pill">${escapeHtml(doc.document_type || 'Unknown')}</span></td>
        <td><span class="chunk-count">${Number(doc.chunk_count).toLocaleString()}</span></td>
        <td class="text-end"><button class="document-open-button" data-open-doc="${escapeAttribute(doc.doc_id)}" aria-label="Open ${escapeAttribute(displayDocumentTitle(doc))}" title="Open document">↗</button></td>
      </tr>`).join('');
  } catch (error) {
    $('#document-count-label').textContent = 'Unable to load documents';
    console.error(error);
  }
}

$('#documents-table').addEventListener('click', (event) => {
  const button = event.target.closest('[data-open-doc]');
  if (!button) return;
  const document = documentRecords.find((item) => item.doc_id === button.dataset.openDoc);
  if (document) openDocument({ ...document, page_start: 1, section: 'Document preview' });
});

$('#document-filter').addEventListener('input', (event) => {
  const query = event.target.value.trim().toLowerCase();
  $$('#documents-table tr').forEach((row) => { row.hidden = !row.dataset.search.includes(query); });
});

async function openDocument(source) {
  const page = source.page_start || 1;
  $('#drawer-type').textContent = `${source.document_type || 'SOURCE'} DOCUMENT`;
  $('#document-drawer-title').textContent = source.title || source.filename;
  $('#drawer-page').textContent = `${source.filename || ''}${page ? ` · Page ${page}` : ''}${source.section ? ` · ${source.section}` : ''}`;
  $('#pdf-frame').classList.add('d-none');
  $('#pdf-unavailable').classList.remove('d-none');
  $('#pdf-unavailable h3').textContent = 'Opening source…';
  $('#pdf-unavailable p').textContent = 'Checking for the original PDF.';
  bootstrap.Offcanvas.getOrCreateInstance($('#document-drawer')).show();
  if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
  try {
    const url = `/api/documents/${encodeURIComponent(source.doc_id)}/pdf?page=${page}`;
    const response = await api(url);
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || 'The original PDF is not available yet.');
    }
    const blob = await response.blob();
    currentObjectUrl = URL.createObjectURL(blob);
    $('#pdf-frame').src = `${currentObjectUrl}#page=${page}&toolbar=0&navpanes=0`;
    $('#pdf-frame').classList.remove('d-none');
    $('#pdf-unavailable').classList.add('d-none');
  } catch (error) {
    $('#pdf-unavailable h3').textContent = 'PDF not available yet';
    $('#pdf-unavailable p').textContent = error.message;
  }
}

$('#suggestions').addEventListener('click', (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  $('#question-input').value = button.textContent;
  $('#question-input').focus();
});

$('#question-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = $('#question-input').value.trim();
  if (!question) return;
  const button = $('#ask-button');
  const errorBox = $('#ask-error');
  button.disabled = true;
  errorBox.classList.add('d-none');
  $('#answer-empty').classList.add('d-none');
  $('#answer-card').classList.remove('d-none');
  $('#answer-text').textContent = '';
  $('#answer-text').dataset.rawAnswer = '';
  $('#source-list').innerHTML = '';
  $('#source-count').textContent = '';
  $('#answer-feedback').classList.add('d-none');
  $('#feedback-status').textContent = '';
  activeQuestionId = null;
  $('#answer-state').textContent = 'Finding relevant passages…';
  try {
    const response = await api('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, doc_id: $('#search-scope').value || null }),
    });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      throw new Error(result.detail || 'Question could not be processed.');
    }
    const result = await readAnswerStream(response);
    $('#answer-state').textContent = result.status === 'completed' ? 'Complete' : 'Needs attention';
    analyticsLoaded = false;
    await loadRecentQuestions();
    if (!$('#view-history').classList.contains('d-none')) await loadQuestionHistory();
    if (!$('#view-analytics').classList.contains('d-none')) await loadAnalytics();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove('d-none');
    $('#answer-state').textContent = 'Could not answer';
  } finally {
    button.disabled = false;
  }
});

async function readAnswerStream(response) {
  if (!response.body) throw new Error('This browser does not support streamed answers.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let status = 'interrupted';
  const handleEvent = (block) => {
    const lines = block.split('\n');
    const name = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
    const payload = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
    if (!name || !payload) return;
    const data = JSON.parse(payload);
    if (name === 'sources') {
      renderSources(data);
      $('#answer-state').textContent = 'Writing answer…';
    } else if (name === 'token') {
      const current = $('#answer-text').dataset.rawAnswer || '';
      const updated = current + (data.text || '');
      $('#answer-text').dataset.rawAnswer = updated;
      $('#answer-text').innerHTML = renderAnswerMarkdown(updated);
    } else if (name === 'error') {
      status = 'failed';
      $('#ask-error').textContent = data.message || 'Answer generation failed.';
      $('#ask-error').classList.remove('d-none');
    } else if (name === 'done') {
      activeQuestionId = data.question_id;
      status = data.status || status;
      if (status === 'completed' && activeQuestionId) $('#answer-feedback').classList.remove('d-none');
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';
    blocks.forEach(handleEvent);
    if (done) break;
  }
  if (buffer.trim()) handleEvent(buffer);
  return { status };
}

function renderSources(sources) {
  $('#source-count').textContent = `(${sources.length})`;
  $('#source-list').innerHTML = sources.map((source) => `
    <button type="button" class="source-row" data-source="${escapeAttribute(JSON.stringify(source))}">
      <span class="source-icon">▤</span>
      <span class="source-meta"><strong>[${escapeHtml(source.citation)}] ${escapeHtml(source.title)}</strong><small>Page ${source.page_start ?? '—'} · ${escapeHtml(source.section || source.document_type || 'Source passage')}</small></span>
      <span class="source-open">Open ↗</span>
    </button>`).join('');
}

$('#source-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-source]');
  if (!button) return;
  openDocument(JSON.parse(button.dataset.source));
});

async function loadAnalytics() {
  try {
    const selectedFamily = $('#analytics-family-filter').value;
    const response = await api(`/api/analytics?family=${encodeURIComponent(selectedFamily)}&days_offset=${analyticsChartOffset}&question_page=${analyticsQuestionPage}`);
    if (response.status === 403) {
      $('#analytics-nav').classList.add('d-none');
      selectView('ask');
      return;
    }
    if (!response.ok) throw new Error('Analytics could not be loaded.');
    const stats = await response.json();
    $('#analytics-docs').textContent = Number(stats.documents).toLocaleString();
    $('#analytics-chunks').textContent = Number(stats.chunks).toLocaleString();
    $('#analytics-today').textContent = Number(stats.questions_today).toLocaleString();
    $('#analytics-total').textContent = `${Number(stats.questions_total).toLocaleString()} total questions`;
    $('#analytics-latency').textContent = stats.average_response_ms ? `${(stats.average_response_ms / 1000).toFixed(1)}s` : '—';
    $('#analytics-accurate').textContent = Number(stats.feedback_accurate || 0).toLocaleString();
    $('#analytics-review').textContent = Number(stats.feedback_needs_review || 0).toLocaleString();
    renderWeeklyChart(stats.daily_questions || [], stats.chart_start, stats.chart_end);
    renderAdminHistory(stats.recent_questions || []);
    renderQuestionPagination(stats.question_pagination || {});
    renderAnalyticsFamilyFilter(stats.document_families || [], stats.selected_family || '');
    analyticsChartOffset = Number(stats.days_offset || 0);
    $('#chart-next').disabled = analyticsChartOffset === 0;
    $('#chart-date-range').textContent = `${formatChartDate(stats.chart_start)} – ${formatChartDate(stats.chart_end)}`;
    renderDeveloperAnalytics(stats);
    analyticsLoaded = true;
  } catch (error) {
    $('#weekly-chart').innerHTML = `<div class="text-danger small">${escapeHtml(error.message)}</div>`;
  }
}

function renderQuestionPagination(pagination) {
  analyticsQuestionPage = Number(pagination.page || 1);
  const pages = Number(pagination.pages || 1);
  const total = Number(pagination.total || 0);
  $('#questions-page-label').textContent = `Page ${analyticsQuestionPage} of ${pages} · ${total.toLocaleString()} questions`;
  $('#questions-previous').disabled = analyticsQuestionPage <= 1;
  $('#questions-next').disabled = analyticsQuestionPage >= pages;
}

function renderAnalyticsFamilyFilter(families, selected) {
  const filter = $('#analytics-family-filter');
  filter.innerHTML = '<option value="">All families</option>' + families.map((family) =>
    `<option value="${escapeAttribute(family)}">${escapeHtml(family)}</option>`).join('');
  filter.value = selected;
}

function renderDeveloperAnalytics(stats) {
  const panel = $('#developer-analytics');
  panel.classList.toggle('d-none', !stats.developer_analytics_enabled);
  if (!stats.developer_analytics_enabled) return;
  const performance = stats.performance || {};
  const stages = [
    ['Query embedding', performance.embedding_ms],
    ['Vector search', performance.vector_search_ms],
    ['Lexical search', performance.lexical_search_ms],
    ['RRF + MMR', performance.fusion_mmr_ms],
    ['Neighbor expansion', performance.neighbor_expansion_ms],
    ['Retrieval total', performance.retrieval_total_ms],
    ['OpenAI first token', performance.openai_ttft_ms],
    ['OpenAI generation', performance.openai_generation_ms],
  ];
  $('#performance-grid').innerHTML = stages.map(([label, value]) => `
    <div class="performance-stat"><span>${escapeHtml(label)}</span><strong>${formatDuration(value)}</strong></div>`).join('');
  $('#token-summary').innerHTML = `
    <div><span>Total input tokens</span><strong>${formatNumber(performance.input_tokens)}</strong></div>
    <div><span>Total output tokens</span><strong>${formatNumber(performance.output_tokens)}</strong></div>
    <div><span>Total tokens</span><strong>${formatNumber(performance.total_tokens)}</strong></div>
    <div><span>Average per answer</span><strong>${formatNumber(performance.average_tokens)}</strong></div>`;
  const rows = stats.slowest_questions || [];
  $('#slowest-questions').innerHTML = rows.length ? rows.map((item) => {
    const timings = item.performance || {};
    return `<tr>
      <td><strong>${escapeHtml(item.question)}</strong><small>${escapeHtml(item.username)} · ${escapeHtml(formatDate(item.created_at))}</small></td>
      <td>${escapeHtml((item.families || []).join(', ') || '—')}</td>
      <td>${formatDuration(timings.retrieval_total_ms)}</td>
      <td>${formatDuration(timings.openai_ttft_ms)}</td>
      <td>${formatDuration(timings.openai_generation_ms)}</td>
      <td><strong>${formatDuration(item.elapsed_ms)}</strong></td>
      <td>${formatNumber(item.total_tokens)}</td>
    </tr>`;
  }).join('') : '<tr><td colspan="7" class="text-secondary">New questions will appear here after instrumentation is enabled.</td></tr>';
}

function formatDuration(value) {
  if (value === null || value === undefined) return '—';
  const milliseconds = Number(value);
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(2)}s` : `${Math.round(milliseconds)}ms`;
}

function formatNumber(value) {
  return value === null || value === undefined ? '—' : Number(value).toLocaleString();
}

$('#analytics-family-filter').addEventListener('change', () => {
  analyticsLoaded = false;
  loadAnalytics();
});

$('#chart-previous').addEventListener('click', () => {
  analyticsChartOffset += 30;
  analyticsLoaded = false;
  loadAnalytics();
});

$('#chart-next').addEventListener('click', () => {
  analyticsChartOffset = Math.max(0, analyticsChartOffset - 30);
  analyticsLoaded = false;
  loadAnalytics();
});

$('#questions-previous').addEventListener('click', () => {
  if (analyticsQuestionPage <= 1) return;
  analyticsQuestionPage -= 1;
  analyticsLoaded = false;
  loadAnalytics();
});

$('#questions-next').addEventListener('click', () => {
  analyticsQuestionPage += 1;
  analyticsLoaded = false;
  loadAnalytics();
});

function renderWeeklyChart(days, chartStart, chartEnd) {
  const counts = new Map(days.map((item) => [item.date, item.count]));
  const end = chartEnd ? new Date(`${chartEnd}T12:00:00+05:30`) : new Date();
  const values = Array.from({ length: 30 }, (_, index) => {
    const day = new Date(end.getTime() - (29 - index) * 24 * 60 * 60 * 1000);
    const iso = dateKeyInIST(day);
    return { date: iso, label: day.toLocaleDateString(undefined, { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' }), count: counts.get(iso) || 0 };
  });
  const max = Math.max(1, ...values.map((item) => item.count));
  $('#weekly-chart').innerHTML = values.map((item) => `
    <div class="chart-day" tabindex="0" data-tooltip="${item.count} question${item.count === 1 ? '' : 's'}" aria-label="${item.label}: ${item.count} questions">
      <div class="chart-bar-wrap"><div class="chart-bar" style="height:${Math.max(item.count ? 8 : 2, (item.count / max) * 100)}%"></div></div>
      <span>${item.label}</span>
    </div>`).join('');
  const scroller = $('#chart-scroll');
  requestAnimationFrame(() => { scroller.scrollLeft = scroller.scrollWidth; });
}

function formatChartDate(value) {
  if (!value) return '—';
  return new Date(`${value}T12:00:00+05:30`).toLocaleDateString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata',
  });
}

async function loadQuestionHistory() {
  const container = $('#question-history-list');
  container.innerHTML = '<div class="text-secondary small">Loading history…</div>';
  try {
    const response = await api('/api/questions');
    if (!response.ok) throw new Error('Could not load question history.');
    const data = await response.json();
    renderQuestionHistory(data.questions || []);
  } catch (error) {
    container.innerHTML = `<div class="text-danger small">${escapeHtml(error.message)}</div>`;
  }
}

async function loadRecentQuestions() {
  try {
    const response = await api('/api/questions');
    if (!response.ok) return;
    const data = await response.json();
    const recent = (data.questions || []).slice(0, 5);
    const panel = $('#recent-questions-panel');
    panel.classList.toggle('d-none', recent.length === 0);
    $('#recent-questions-list').innerHTML = recent.map((item) => `
      <button type="button" class="recent-question" data-reask="${escapeAttribute(item.question)}">
        <span>${escapeHtml(item.question)}</span><small title="${escapeAttribute(formatDateLong(item.created_at))}">${escapeHtml(formatDate(item.created_at))}${item.feedback === 'needs_review' ? ' · flagged for review' : ''}</small>
      </button>`).join('');
  } catch (error) {
    console.error('Could not load recent questions:', error);
  }
}

$('#recent-questions-list').addEventListener('click', (event) => {
  const button = event.target.closest('[data-reask]');
  if (!button) return;
  $('#question-input').value = button.dataset.reask;
  $('#question-input').focus();
  $('#question-input').scrollIntoView({ behavior: 'smooth', block: 'center' });
});

function renderQuestionHistory(items) {
  items = [...items].sort((left, right) => new Date(right.created_at) - new Date(left.created_at));
  const container = $('#question-history-list');
  $('#history-count-label').textContent = `${items.length} saved`;
  if (!items.length) {
    container.innerHTML = '<div class="empty-state">No saved questions yet. Ask a question and it will appear here.</div>';
    return;
  }
  container.innerHTML = items.map((item) => `
    <article class="history-card">
      <div class="history-card-top"><span class="history-date" title="${escapeAttribute(formatDateLong(item.created_at))}">${escapeHtml(formatDate(item.created_at))}</span><span class="history-duration">${(Number(item.elapsed_ms) / 1000).toFixed(1)}s</span></div>
      <h2>${escapeHtml(item.question)}</h2>
      <p class="history-answer">${renderAnswerMarkdown(item.answer || 'No answer was generated.')}</p>
      ${renderHistorySources(item.sources || [])}
      ${renderFeedbackControls(item.id, item.feedback)}
    </article>`).join('');
}

function renderHistorySources(sources) {
  if (!sources.length) return '<div class="history-no-source">No supporting passages were retrieved.</div>';
  return `<div class="history-sources">${sources.map((source) => `
    <button type="button" class="history-source" data-history-source="${escapeAttribute(JSON.stringify(source))}">
      [${escapeHtml(source.citation)}] ${escapeHtml(source.title)} · p. ${escapeHtml(source.page_start ?? '—')}
    </button>`).join('')}</div>`;
}

function renderFeedbackControls(id, feedback) {
  const accurate = feedback === 'accurate' ? ' selected' : '';
  const review = feedback === 'needs_review' ? ' selected' : '';
  return `<div class="history-feedback"><span>${feedback ? `Review: ${feedback === 'accurate' ? 'Looks right' : 'Needs review'}` : 'Is this answer supported by the source?'}</span>
    <div class="d-flex gap-2"><button class="btn btn-sm btn-outline-success${accurate}" data-review-id="${id}" data-feedback="accurate">Looks right</button><button class="btn btn-sm btn-outline-warning${review}" data-review-id="${id}" data-feedback="needs_review">Needs review</button></div></div>`;
}

function renderAdminHistory(items) {
  items = [...items].sort((left, right) => new Date(right.created_at) - new Date(left.created_at));
  const container = $('#admin-history-list');
  if (!items.length) {
    container.innerHTML = '<div class="empty-state">No saved questions yet.</div>';
    return;
  }
  container.innerHTML = `<div class="table-responsive"><table class="table align-middle admin-history-table"><thead><tr><th>QUESTION / ANSWER</th><th>ASKED BY</th><th>REVIEW</th></tr></thead><tbody>${items.map((item) => `
    <tr><td><strong>${escapeHtml(item.question)}</strong><div class="admin-answer-preview">${renderAnswerMarkdown(item.answer || 'No answer was generated.')}</div></td><td>${escapeHtml(item.username)}<small title="${escapeAttribute(formatDateLong(item.created_at))}">${escapeHtml(formatDate(item.created_at))}</small></td><td>${renderFeedbackControls(item.id, item.feedback)}</td></tr>`).join('')}</tbody></table></div>`;
}

async function submitFeedback(questionId, feedback) {
  const response = await api(`/api/questions/${questionId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  });
  if (!response.ok) throw new Error('Could not save answer review.');
  if (activeQuestionId === questionId) {
    $('#feedback-status').textContent = feedback === 'accurate' ? 'Thanks — marked looks right.' : 'Thanks — flagged for review.';
  }
  if (!$('#view-history').classList.contains('d-none')) loadQuestionHistory();
  if (analyticsLoaded) {
    analyticsLoaded = false;
    loadAnalytics();
  }
}

$('#answer-feedback').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-feedback]');
  if (!button || !activeQuestionId) return;
  try {
    await submitFeedback(activeQuestionId, button.dataset.feedback);
    $('#feedback-status').textContent = button.dataset.feedback === 'accurate' ? 'Thanks — marked looks right.' : 'Thanks — flagged for review.';
  } catch (error) {
    $('#feedback-status').textContent = error.message;
  }
});

$('#question-history-list').addEventListener('click', async (event) => {
  const sourceButton = event.target.closest('[data-history-source]');
  if (sourceButton) {
    openDocument(JSON.parse(sourceButton.dataset.historySource));
    return;
  }
  const reviewButton = event.target.closest('[data-review-id]');
  if (reviewButton) {
    try { await submitFeedback(Number(reviewButton.dataset.reviewId), reviewButton.dataset.feedback); }
    catch (error) { window.alert(error.message); }
  }
});

$('#admin-history-list').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-review-id]');
  if (!button) return;
  try { await submitFeedback(Number(button.dataset.reviewId), button.dataset.feedback); }
  catch (error) { window.alert(error.message); }
});

$('#refresh-history').addEventListener('click', loadQuestionHistory);

function formatDate(value) {
  const date = new Date(value);
  const today = new Date();
  const sameDay = dateKeyInIST(date) === dateKeyInIST(today);
  return sameDay
    ? date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' })
    : date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', timeZone: 'Asia/Kolkata' });
}

function formatDateLong(value) {
  return `${new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' })} IST`;
}

function dateKeyInIST(value) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(value);
}

function displayDocumentTitle(doc) {
  const title = String(doc.title || '').trim();
  const filename = String(doc.filename || '').trim();
  if (title && title !== filename && title.toLowerCase() !== filename.replace(/\.md$/i, '').toLowerCase()) return title;
  return filename
    .replace(/\.md$/i, '')
    .replace(/_{2,}/g, ' — ')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}

function renderAnswerMarkdown(value) {
  return escapeHtml(value).replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>');
}

function escapeAttribute(value) { return escapeHtml(value); }

boot();
